"""Train six hotspot-forecast classifiers + seasonal and persistence baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.hotspot_forecast import (
    COMPARISON_PATH,
    DATASET_PATH,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    SELECTION_PATH,
    SPLIT_PATH,
    model_hash,
)
from vela.onset_models import (
    build_classifiers,
    classification_report_block,
    choose_threshold_on_validation,
    compare_on_validation,
    predict_proba_positive,
    seasonal_baseline_probs,
)
from vela.settings import DATA_DIR

SEED = 0


def _json_default(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


def _impute_fit(matrix: np.ndarray) -> list[float]:
    means = []
    for col in range(matrix.shape[1]):
        vals = matrix[:, col]
        finite = vals[np.isfinite(vals)]
        means.append(float(np.mean(finite)) if len(finite) else 0.0)
    return means


def _impute_apply(matrix: np.ndarray, means: list[float]) -> np.ndarray:
    out = matrix.copy()
    for col, mean in enumerate(means):
        mask = ~np.isfinite(out[:, col])
        out[mask, col] = mean
    return out


def persistence_probs(frame: pd.DataFrame) -> np.ndarray:
    return frame["persistence_heat_yesterday"].fillna(0).to_numpy(dtype=float)


def reliability_table(y_true: np.ndarray, y_prob: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        if i == bins - 1:
            mask = (y_prob >= lo) & (y_prob <= hi)
        else:
            mask = (y_prob >= lo) & (y_prob < hi)
        n = int(mask.sum())
        rows.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": n,
                "mean_predicted": None if n == 0 else float(np.mean(y_prob[mask])),
                "observed_rate": None if n == 0 else float(np.mean(y_true[mask])),
            }
        )
    return rows


def run() -> dict:
    if not DATASET_PATH.is_file():
        raise SystemExit(f"Dataset missing: {DATASET_PATH}. Run build_hotspot_forecast_dataset first.")
    frame = pd.read_parquet(DATASET_PATH)
    train = frame[frame["split"] == "train"].copy()
    valid = frame[frame["split"] == "validation"].copy()
    test = frame[frame["split"] == "test"].copy()
    if len(train) < 50 or len(valid) < 20:
        return {
            "status": "refused_insufficient_rows",
            "row_counts": {
                "train": int(len(train)),
                "validation": int(len(valid)),
                "test": int(len(test)),
            },
        }

    x_train_raw = train[FEATURE_NAMES].to_numpy(dtype=float)
    x_valid_raw = valid[FEATURE_NAMES].to_numpy(dtype=float)
    x_test_raw = test[FEATURE_NAMES].to_numpy(dtype=float)
    means = _impute_fit(x_train_raw)
    x_train = _impute_apply(x_train_raw, means)
    x_valid = _impute_apply(x_valid_raw, means)
    x_test = _impute_apply(x_test_raw, means)
    y_train = train["label"].to_numpy(dtype=int)
    y_valid = valid["label"].to_numpy(dtype=int)
    y_test = test["label"].to_numpy(dtype=int)

    season_train = [
        f"{str(r.issue_date_ph)[5:7]}|{'dry' if int(str(r.issue_date_ph)[5:7]) in {1,2,3,4,11,12} else 'wet'}"
        for r in train.itertuples()
    ]
    season_valid = [
        f"{str(r.issue_date_ph)[5:7]}|{'dry' if int(str(r.issue_date_ph)[5:7]) in {1,2,3,4,11,12} else 'wet'}"
        for r in valid.itertuples()
    ]
    season_test = [
        f"{str(r.issue_date_ph)[5:7]}|{'dry' if int(str(r.issue_date_ph)[5:7]) in {1,2,3,4,11,12} else 'wet'}"
        for r in test.itertuples()
    ]

    comparison = compare_on_validation(
        x_train,
        y_train,
        x_valid,
        y_valid,
        season_keys_train=season_train,
        season_keys_valid=season_valid,
        random_state=SEED,
    )

    # Baselines on validation
    seasonal = seasonal_baseline_probs(y_train, season_train, season_valid)
    persistence = persistence_probs(valid)
    baseline_rows = [
        {
            "name": "regional_seasonal_detection_rate",
            "metrics": classification_report_block(
                y_valid, seasonal, threshold=0.5, baseline_prob=seasonal
            ),
        },
        {
            "name": "persistence_recent_heat",
            "metrics": classification_report_block(
                y_valid, persistence, threshold=0.5, baseline_prob=seasonal
            ),
        },
    ]

    # Include baselines in winner selection by Brier
    candidates = []
    for row in comparison["classifiers"]:
        if row.get("metrics"):
            candidates.append({"kind": "classifier", **row})
    for row in baseline_rows:
        candidates.append({"kind": "baseline", "threshold": 0.5, **row})

    def sort_key(row):
        m = row["metrics"]
        return (m["brier_score"] if m["brier_score"] is not None else 1e9,)

    ranked = sorted(candidates, key=sort_key)
    winner = ranked[0]
    winner_name = winner["name"]

    artifact = DATA_DIR / "models" / "philippines_hotspot_winner.joblib"
    if winner.get("kind") == "classifier":
        positive_count = int(np.sum(y_train == 1))
        cv_folds = max(2, min(3, positive_count)) if positive_count else 2
        model = build_classifiers(random_state=SEED, cv_folds=cv_folds)[winner_name]
        model.fit(x_train, y_train)
        threshold = float(winner["threshold"])
        bundle = {
            "kind": "classifier",
            "model": model,
            "feature_names": FEATURE_NAMES,
            "imputer_means": means,
            "threshold": threshold,
            "winner_name": winner_name,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "seed": SEED,
        }
        joblib.dump(bundle, artifact)
        # Holdout probs
        y_prob = predict_proba_positive(model, x_test)
    else:
        threshold = 0.5
        bundle = {
            "kind": "baseline",
            "winner_name": winner_name,
            "feature_names": FEATURE_NAMES,
            "imputer_means": means,
            "threshold": threshold,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "seed": SEED,
        }
        joblib.dump(bundle, artifact)
        if winner_name == "persistence_recent_heat":
            y_prob = persistence_probs(test)
        else:
            y_prob = seasonal_baseline_probs(y_train, season_train, season_test)

    seasonal_test = seasonal_baseline_probs(y_train, season_train, season_test)
    holdout = classification_report_block(
        y_test, y_prob, threshold=threshold, baseline_prob=seasonal_test
    )
    recent = test["recent_heat"].to_numpy(dtype=int) == 1
    holdout_recent = (
        None
        if not recent.any()
        else classification_report_block(
            y_test[recent], y_prob[recent], threshold=threshold, baseline_prob=seasonal_test[recent]
        )
    )
    holdout_cold = (
        None
        if (~recent).sum() == 0
        else classification_report_block(
            y_test[~recent],
            y_prob[~recent],
            threshold=threshold,
            baseline_prob=seasonal_test[~recent],
        )
    )

    recorded = datetime.now(timezone.utc).isoformat()
    payload = {
        "status": "research_trained",
        "state": "holdout_evaluated",
        "recorded_at_utc": recorded,
        "seed": SEED,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_path": str(DATASET_PATH),
        "split_manifest": str(SPLIT_PATH),
        "data_version": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()[:16],
        "row_counts": {
            "train": int(len(train)),
            "validation": int(len(valid)),
            "test": int(len(test)),
            "positive_train": int(y_train.sum()),
            "positive_valid": int(y_valid.sum()),
            "positive_test": int(y_test.sum()),
        },
        "classifiers": comparison["classifiers"],
        "baselines": baseline_rows,
        "leaderboard": [
            {"name": row["name"], "kind": row.get("kind"), "brier": row["metrics"]["brier_score"]}
            for row in ranked
        ],
        "winner": {
            "name": winner_name,
            "kind": winner.get("kind"),
            "threshold": threshold,
            "why": (
                "Lowest validation Brier among six classifiers and two baselines "
                "(seasonal rate, persistence). Not chosen by accuracy≈F1."
            ),
            "validation_metrics": winner["metrics"],
        },
        "holdout": {
            "metrics": holdout,
            "reliability_table": reliability_table(y_test, y_prob),
            "recent_heat_squares": holdout_recent,
            "no_recent_heat_squares": holdout_cold,
            "scored_on": "adequately observed square-days only (positives + covered negatives)",
        },
        "model_artifact": str(artifact),
        "model_hash": model_hash(artifact),
        "approved_for_serving": True,
        "public_label": "Chance of satellite-detected heat",
    }
    COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPARISON_PATH.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
    SELECTION_PATH.write_text(
        json.dumps(
            {
                "status": "selected",
                "state": "holdout_evaluated",
                "chosen_model": winner_name,
                "kind": winner.get("kind"),
                "threshold": threshold,
                "model_artifact": str(artifact),
                "model_hash": payload["model_hash"],
                "approved_for_serving": True,
                "public_label": "Chance of satellite-detected heat",
                "comparison_path": str(COMPARISON_PATH),
                "recorded_at_utc": recorded,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    payload = run()
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "winner": None if not payload.get("winner") else payload["winner"].get("name"),
                "leaderboard": payload.get("leaderboard"),
                "holdout_brier": None
                if not payload.get("holdout")
                else payload["holdout"]["metrics"].get("brier_score"),
                "row_counts": payload.get("row_counts"),
                "approved_for_serving": payload.get("approved_for_serving"),
            },
            indent=2,
            default=_json_default,
        )
    )


if __name__ == "__main__":
    main()
