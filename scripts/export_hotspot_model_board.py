"""Persist all six Maguindanao classifiers + baselines for the past-date model board.

Does not overwrite philippines_hotspot_selection.json. Island-wide selection stays separate.
"""

from __future__ import annotations

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

from scripts.train_hotspot_forecast import (  # noqa: E402
    SEED,
    _impute_apply,
    _impute_fit,
    _json_default,
    enrich_metrics,
    persistence_probs,
)
from vela.hotspot_forecast import (  # noqa: E402
    COMPARISON_PATH,
    DATASET_PATH,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    MODELS_DIR,
)
from vela.onset_models import (  # noqa: E402
    build_classifiers,
    classification_report_block,
    predict_proba_positive,
    seasonal_baseline_probs,
)


def main() -> None:
    if not DATASET_PATH.is_file():
        raise SystemExit(f"Missing dataset: {DATASET_PATH}")
    frame = pd.read_parquet(DATASET_PATH)
    train = frame[frame["split"] == "train"].copy()
    valid = frame[frame["split"] == "validation"].copy()
    x_train_raw = train[FEATURE_NAMES].to_numpy(dtype=float)
    x_valid_raw = valid[FEATURE_NAMES].to_numpy(dtype=float)
    means = _impute_fit(x_train_raw)
    x_train = _impute_apply(x_train_raw, means)
    x_valid = _impute_apply(x_valid_raw, means)
    y_train = train["label"].to_numpy(dtype=int)
    y_valid = valid["label"].to_numpy(dtype=int)
    season_train = [
        f"{str(r.issue_date_ph)[5:7]}|{'dry' if int(str(r.issue_date_ph)[5:7]) in {1,2,3,4,11,12} else 'wet'}"
        for r in train.itertuples()
    ]
    season_valid = [
        f"{str(r.issue_date_ph)[5:7]}|{'dry' if int(str(r.issue_date_ph)[5:7]) in {1,2,3,4,11,12} else 'wet'}"
        for r in valid.itertuples()
    ]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    positive_count = int(np.sum(y_train == 1))
    cv_folds = max(2, min(3, positive_count)) if positive_count else 2
    fitted = build_classifiers(random_state=SEED, cv_folds=cv_folds)
    board_models = []
    for name, model in fitted.items():
        model.fit(x_train, y_train)
        proba = predict_proba_positive(model, x_valid)
        metrics = enrich_metrics(
            classification_report_block(y_valid, proba, threshold=0.5),
            y_valid,
            proba,
        )
        path = MODELS_DIR / f"classifier_{name}.joblib"
        joblib.dump(
            {
                "kind": "classifier",
                "model": model,
                "feature_names": FEATURE_NAMES,
                "imputer_means": means,
                "threshold": 0.5,
                "winner_name": name,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "coverage_rule_version": "hotspot_coverage_v2_1",
                "seed": SEED,
            },
            path,
        )
        board_models.append(
            {
                "name": name,
                "kind": "classifier",
                "artifact": str(path),
                "validation_metrics": metrics,
            }
        )
    seasonal = seasonal_baseline_probs(y_train, season_train, season_valid)
    persistence = persistence_probs(valid)
    rate = float(y_train.mean()) if len(y_train) else 0.0
    for name, proba in (
        ("regional_seasonal_detection_rate", seasonal),
        ("persistence_recent_heat", persistence),
    ):
        metrics = enrich_metrics(
            classification_report_block(y_valid, proba, threshold=0.5, baseline_prob=seasonal),
            y_valid,
            proba,
        )
        path = MODELS_DIR / f"baseline_{name}.joblib"
        joblib.dump(
            {
                "kind": "baseline",
                "winner_name": name,
                "feature_names": FEATURE_NAMES,
                "imputer_means": means,
                "threshold": 0.5,
                "global_rate": rate,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "coverage_rule_version": "hotspot_coverage_v2_1",
                "seed": SEED,
            },
            path,
        )
        board_models.append(
            {
                "name": name,
                "kind": "baseline",
                "artifact": str(path),
                "validation_metrics": metrics,
            }
        )
    manifest = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "maguindanao_v2_1_control",
        "models": board_models,
        "comparison_path": str(COMPARISON_PATH),
        "note": (
            "Board artifacts for past/today multi-model UI. Maguindanao selection unchanged; "
            "island-wide selection is separate until promotion criteria are met."
        ),
    }
    (MODELS_DIR / "board_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=_json_default) + "\n", encoding="utf-8"
    )
    # Separate island selection stub — does not promote percentages island-wide.
    island_sel = MODELS_DIR / "mindanao_island_selection.json"
    island_sel.write_text(
        json.dumps(
            {
                "status": "pending_coverage",
                "state": "serving_blocked",
                "chosen_model": None,
                "approved_for_serving": False,
                "study_id": "mindanao_island_v1",
                "reason": (
                    "Island-wide clear-pass negatives and holdout evaluation are not yet complete. "
                    "Maguindanao v2.1 percentages remain the only claimable percentage zone."
                ),
                "control_selection": str(ROOT / "data" / "models" / "philippines_hotspot_selection.json"),
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"board_models": len(board_models), "manifest": str(MODELS_DIR / "board_manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
