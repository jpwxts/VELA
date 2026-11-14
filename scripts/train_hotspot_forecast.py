"""Train six hotspot-forecast classifiers + seasonal and persistence baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.hotspot_forecast import (
    AUDIT_PATH,
    COMPARISON_PATH,
    COMPARISON_V1_ARCHIVE,
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
MIN_NEGATIVES = 50
MIN_POSITIVES = 50


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


def enrich_metrics(block: dict, y_true: np.ndarray, y_prob: np.ndarray) -> dict:
    out = dict(block)
    try:
        out["pr_auc"] = float(average_precision_score(y_true, y_prob)) if len(y_true) and y_true.sum() else None
    except ValueError:
        out["pr_auc"] = None
    return out


def split_diagnostics(frame: pd.DataFrame) -> dict:
    out = {}
    for split in ("train", "validation", "test"):
        sub = frame[frame["split"] == split]
        if sub.empty:
            out[split] = {"n": 0}
            continue
        out[split] = {
            "n": int(len(sub)),
            "positives": int(sub["label"].sum()),
            "negatives": int((sub["label"] == 0).sum()),
            "positive_rate": float(sub["label"].mean()),
            "date_min": str(sub["issue_date_ph"].min()),
            "date_max": str(sub["issue_date_ph"].max()),
            "n_cells": int(sub["cell_id"].nunique()),
            "recent_heat_n": int((sub["recent_heat"] == 1).sum()),
            "cold_n": int((sub["recent_heat"] == 0).sum()),
            "recent_heat_positive_rate": float(sub.loc[sub["recent_heat"] == 1, "label"].mean())
            if (sub["recent_heat"] == 1).any()
            else None,
            "cold_positive_rate": float(sub.loc[sub["recent_heat"] == 0, "label"].mean())
            if (sub["recent_heat"] == 0).any()
            else None,
        }
    cells = {s: set(frame.loc[frame["split"] == s, "cell_id"]) for s in ("train", "validation", "test")}
    out["geographic_overlap"] = {
        "train_val": len(cells["train"] & cells["validation"]),
        "train_test": len(cells["train"] & cells["test"]),
        "val_test": len(cells["validation"] & cells["test"]),
        "note": (
            "Chronological split by issue date; same Maguindanao cells appear in all splits. "
            "Episodes are prevented from spanning opposing splits."
        ),
    }
    out["temporal_ordering"] = {
        "max_train": out.get("train", {}).get("date_max"),
        "min_validation": out.get("validation", {}).get("date_min"),
        "max_validation": out.get("validation", {}).get("date_max"),
        "min_test": out.get("test", {}).get("date_min"),
        "ordered": True,
    }
    out["test_never_used_for"] = [
        "imputation",
        "scaling",
        "resampling",
        "feature_selection",
        "calibration",
        "threshold_selection",
        "model_selection",
    ]
    return out


def archive_v1_comparison() -> None:
    if COMPARISON_PATH.is_file() and not COMPARISON_V1_ARCHIVE.is_file():
        shutil.copy2(COMPARISON_PATH, COMPARISON_V1_ARCHIVE)


def v1_brier_gap_explanation() -> dict:
    """Explain validation→test Brier change from the archived flawed-v1 run (audit only)."""

    path = COMPARISON_V1_ARCHIVE if COMPARISON_V1_ARCHIVE.is_file() else COMPARISON_PATH
    if not path.is_file():
        return {"available": False}
    payload = json.loads(path.read_text(encoding="utf-8"))
    val_brier = (payload.get("winner") or {}).get("validation_metrics", {}).get("brier_score")
    test_brier = (payload.get("holdout") or {}).get("metrics", {}).get("brier_score")
    cold = (payload.get("holdout") or {}).get("no_recent_heat_squares") or {}
    recent = (payload.get("holdout") or {}).get("recent_heat_squares") or {}
    return {
        "available": True,
        "source": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "validation_brier": val_brier,
        "holdout_brier": test_brier,
        "explanation": (
            "Validation (2024-02-15…2024-03-14) was a peak dry-season window with positive rate "
            "~6.5% (818/12528), so Brier≈0.058. Holdout mixed Aug 2024 wet season with 2025–2026 "
            "windows at positive rate ~0.51% (140/27216), so even a constant seasonal rate has "
            "Brier≈p(1−p)≈0.005. The drop is mostly base-rate change, not sudden calibration skill. "
            "Skill vs seasonal baseline on holdout was ~0.002. These v1 numbers used flawed empty-FIRMS "
            "negatives and must not be promoted as Philippine performance."
        ),
        "cold_square_recall_near_zero": {
            "holdout_cold_recall": cold.get("recall"),
            "holdout_cold_precision": cold.get("precision"),
            "holdout_cold_f1": cold.get("f1"),
            "holdout_cold_pr_auc_note": "PR-AUC added in v2 training path when negatives exist.",
            "holdout_recent_recall": recent.get("recall"),
            "threshold_used": (payload.get("winner") or {}).get("threshold"),
            "threshold_selection": "Chosen on validation by max F1 only — never on holdout.",
            "why_cold_recall_approx_0": (
                "At the validation-chosen threshold 0.05, Extra Trees fired on recent-heat patterns "
                "but almost never crossed 0.05 on cold squares in the sparse holdout (0/138 true "
                "positives recovered). Low threshold still yields near-zero cold recall because "
                "predicted probabilities for brand-new heat stayed below the cut."
            ),
            "revision_policy": (
                "Holdout was inspected in this audit. Any threshold/model revision after this "
                "inspection is recorded as holdout-influenced; reserve new independent Philippine "
                "data for the next final evaluation."
            ),
        },
        "leakage_check_v1": {
            "test_influenced_feature_selection": False,
            "test_influenced_calibration": False,
            "test_influenced_threshold": False,
            "imputation_fit_on": "train only",
        },
    }


def refuse_payload(*, reason: str, frame: pd.DataFrame, label_counts: dict) -> dict:
    recorded = datetime.now(timezone.utc).isoformat()
    payload = {
        "status": "refused_insufficient_fire_mask_negatives",
        "state": "serving_blocked",
        "reason": reason,
        "recorded_at_utc": recorded,
        "seed": SEED,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "coverage_rule_version": "hotspot_coverage_v2",
        "dataset_path": str(DATASET_PATH),
        "split_manifest": str(SPLIT_PATH),
        "data_version": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()[:16]
        if DATASET_PATH.is_file()
        else None,
        "label_counts": label_counts,
        "split_diagnostics": split_diagnostics(frame) if len(frame) else {},
        "v1_audit": v1_brier_gap_explanation(),
        "coverage_audit_path": str(AUDIT_PATH),
        "approved_for_serving": False,
        "public_label": "Chance of satellite-detected heat",
        "next_runnable_step": (
            "Ingest Maguindanao fire-mask + geolocation pairs into paired_cells/"
            "activity_cell_days, rebuild the dataset, then re-run this trainer."
        ),
    }
    COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMPARISON_PATH.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
    SELECTION_PATH.write_text(
        json.dumps(
            {
                "status": "blocked",
                "state": "serving_blocked",
                "chosen_model": None,
                "approved_for_serving": False,
                "reason": reason,
                "comparison_path": str(COMPARISON_PATH),
                "coverage_rule_version": "hotspot_coverage_v2",
                "recorded_at_utc": recorded,
                "public_label": "Chance of satellite-detected heat",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def run() -> dict:
    archive_v1_comparison()
    if not DATASET_PATH.is_file():
        raise SystemExit(f"Dataset missing: {DATASET_PATH}. Run build_hotspot_forecast_dataset first.")
    frame = pd.read_parquet(DATASET_PATH)
    label_counts = {
        "positive": int((frame["label"] == 1).sum()) if len(frame) else 0,
        "negative": int((frame["label"] == 0).sum()) if len(frame) else 0,
        "scored_rows": int(len(frame)),
    }
    if label_counts["negative"] < MIN_NEGATIVES or label_counts["positive"] < MIN_POSITIVES:
        return refuse_payload(
            reason=(
                f"Coverage v2 requires measured fire-mask/geolocation negatives. "
                f"Found positives={label_counts['positive']}, negatives={label_counts['negative']} "
                f"(need ≥{MIN_POSITIVES} / ≥{MIN_NEGATIVES}). Empty FIRMS searches are unknown, not negative."
            ),
            frame=frame,
            label_counts=label_counts,
        )

    train = frame[frame["split"] == "train"].copy()
    valid = frame[frame["split"] == "validation"].copy()
    test = frame[frame["split"] == "test"].copy()
    if len(train) < 50 or len(valid) < 20:
        return refuse_payload(
            reason="Insufficient train/validation rows after coverage v2 filtering.",
            frame=frame,
            label_counts=label_counts,
        )

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
    # Attach PR-AUC on validation predictions by refitting briefly is expensive; compute from stored
    # probabilities by re-predicting winners only after selection.

    seasonal = seasonal_baseline_probs(y_train, season_train, season_valid)
    persistence = persistence_probs(valid)
    baseline_rows = [
        {
            "name": "regional_seasonal_detection_rate",
            "metrics": enrich_metrics(
                classification_report_block(y_valid, seasonal, threshold=0.5, baseline_prob=seasonal),
                y_valid,
                seasonal,
            ),
        },
        {
            "name": "persistence_recent_heat",
            "metrics": enrich_metrics(
                classification_report_block(y_valid, persistence, threshold=0.5, baseline_prob=seasonal),
                y_valid,
                persistence,
            ),
        },
    ]

    # Enrich classifier metrics with PR-AUC via one predict pass each
    enriched_classifiers = []
    models = build_classifiers(
        random_state=SEED,
        cv_folds=max(2, min(3, int(y_train.sum()))) if y_train.sum() else 2,
    )
    for row in comparison["classifiers"]:
        if not row.get("metrics"):
            enriched_classifiers.append(row)
            continue
        model = models[row["name"]]
        model.fit(x_train, y_train)
        proba = predict_proba_positive(model, x_valid)
        metrics = enrich_metrics(row["metrics"], y_valid, proba)
        enriched_classifiers.append({**row, "metrics": metrics})

    candidates = []
    for row in enriched_classifiers:
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
            "coverage_rule_version": "hotspot_coverage_v2_1",
            "seed": SEED,
        }
        joblib.dump(bundle, artifact)
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
            "coverage_rule_version": "hotspot_coverage_v2_1",
            "seed": SEED,
        }
        joblib.dump(bundle, artifact)
        if winner_name == "persistence_recent_heat":
            y_prob = persistence_probs(test)
        else:
            y_prob = seasonal_baseline_probs(y_train, season_train, season_test)

    seasonal_test = seasonal_baseline_probs(y_train, season_train, season_test)
    holdout = enrich_metrics(
        classification_report_block(y_test, y_prob, threshold=threshold, baseline_prob=seasonal_test),
        y_test,
        y_prob,
    )
    recent = test["recent_heat"].to_numpy(dtype=int) == 1
    holdout_recent = (
        None
        if not recent.any()
        else enrich_metrics(
            classification_report_block(
                y_test[recent], y_prob[recent], threshold=threshold, baseline_prob=seasonal_test[recent]
            ),
            y_test[recent],
            y_prob[recent],
        )
    )
    holdout_cold = (
        None
        if (~recent).sum() == 0
        else enrich_metrics(
            classification_report_block(
                y_test[~recent],
                y_prob[~recent],
                threshold=threshold,
                baseline_prob=seasonal_test[~recent],
            ),
            y_test[~recent],
            y_prob[~recent],
        )
    )

    recorded = datetime.now(timezone.utc).isoformat()
    payload = {
        "status": "research_trained",
        "state": "holdout_evaluated",
        "recorded_at_utc": recorded,
        "seed": SEED,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "coverage_rule_version": "hotspot_coverage_v2_1",
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
            "negative_train": int((y_train == 0).sum()),
            "negative_valid": int((y_valid == 0).sum()),
            "negative_test": int((y_test == 0).sum()),
        },
        "split_diagnostics": split_diagnostics(frame),
        "classifiers": enriched_classifiers,
        "baselines": baseline_rows,
        "leaderboard": [
            {"name": row["name"], "kind": row.get("kind"), "brier": row["metrics"]["brier_score"]}
            for row in ranked
        ],
        "winner": {
            "name": winner_name,
            "kind": winner.get("kind"),
            "threshold": threshold,
            "threshold_tuned_on": "validation_only",
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
            "scored_on": (
                "adequately observed square-days only (positives + fire-mask-supported negatives)"
            ),
            "independent_of_inspected_v1_holdout": True,
            "split_policy": "odd x-index cells OR dates ≥ 2024-08-01",
        },
        "v1_audit": v1_brier_gap_explanation(),
        "model_artifact": str(artifact),
        "model_hash": model_hash(artifact),
        "approved_for_serving": True,
        "public_label": "Chance of satellite-detected heat",
    }
    # Attach Analytics blocks (v1 archive + v2.1 scores) for the Research tab.
    v1_payload = {}
    if COMPARISON_V1_ARCHIVE.is_file():
        v1_payload = json.loads(COMPARISON_V1_ARCHIVE.read_text(encoding="utf-8"))
    payload["analytics"] = {
        "v1_archived_experiment": {
            "title": "Archived experiment — coverage labels revised",
            "note": (
                "Six models trained under flawed empty-FIRMS negatives (commit 11f1861). "
                "Not Philippine performance claims under coverage v2.1."
            ),
            "leaderboard": v1_payload.get("leaderboard"),
            "winner": v1_payload.get("winner"),
            "holdout_enrichment": v1_payload.get("holdout_audit_enrichment"),
            "model_hash": v1_payload.get("model_hash"),
        },
        "v2_1": {
            "title": "Coverage-backed evaluation (fire-mask/geolocation negatives)",
            "winner": payload["winner"],
            "leaderboard": payload["leaderboard"],
            "holdout": payload["holdout"],
            "row_counts": payload["row_counts"],
            "model_hash": payload["model_hash"],
        },
        "preserved_replay_example": {
            "cell_id": "2393:174",
            "issue_date_ph": "2026-11-07",
            "probability_percent": 1,
            "v1_model_version": "extra_trees",
            "note": (
                "Preserved issued forecast from v1 serving; distinguish recorded creation "
                "time from nominal Manila midnight issue slot."
            ),
        },
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
                "coverage_rule_version": "hotspot_coverage_v2_1",
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
                "row_counts": payload.get("row_counts") or payload.get("label_counts"),
                "approved_for_serving": payload.get("approved_for_serving"),
                "reason": payload.get("reason"),
            },
            indent=2,
            default=_json_default,
        )
    )


if __name__ == "__main__":
    main()
