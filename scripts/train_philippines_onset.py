"""Train and compare six onset classifiers fairly (Mindanao-first).

Models:
  1. Logistic regression
  2. Decision tree
  3. Random forest
  4. Extra Trees
  5. Histogram gradient boosting
  6. Calibrated support vector machine
Plus a regional seasonal event-rate baseline.

Selection uses validation Brier score relative to the seasonal baseline.
Alert thresholds are chosen on validation only. Research training is distinct
from holdout evaluation and from approval for serving forecasts.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.onset_dataset import build_dataset, write_split_counts
from vela.onset_forecast import (
    AUDIT_PATH,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    SELECTION_PATH,
    SPLIT_PATH,
    TARGET_DEFINITION,
    labels_sufficient,
    load_audit,
)
from vela.onset_models import build_classifiers, compare_on_validation, predict_proba_positive
from vela.settings import DATA_DIR

COMPARISON_PATH = DATA_DIR / "metrics" / "philippines_onset_model_comparison.json"
MODEL_DIR = DATA_DIR / "models"


def _refuse_payload(audit: dict, row_counts: dict | None = None) -> dict:
    return {
        "status": "refused_insufficient_labels",
        "state": "research_blocked",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": TARGET_DEFINITION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "split_manifest": str(SPLIT_PATH.relative_to(ROOT)),
        "row_counts": row_counts,
        "audit_path": str(AUDIT_PATH.relative_to(ROOT)),
        "usable_unique_wildfire_starts": audit.get("usable_unique_wildfire_starts"),
        "square_days_with_credible_reporting_coverage": audit.get(
            "square_days_with_credible_reporting_coverage"
        ),
        "negatives_supported": audit.get("negatives_supported"),
        "winner": None,
        "holdout_evaluation": None,
        "publish_probability": False,
        "approved_for_serving": False,
        "reason": audit.get("publish_blocker"),
        "next_runnable_step": audit.get("next_runnable_step"),
        "harmonization_model_untouched": True,
    }


def run(
    *,
    label_dir: Path,
    comparison_path: Path,
    selection_path: Path,
    split_path: Path,
    model_dir: Path,
    audit_path: Path | None = None,
    allow_synthetic_research: bool = False,
) -> dict:
    audit = load_audit(audit_path) if audit_path else load_audit()
    dataset = build_dataset(label_dir, split_path=split_path)
    write_split_counts(dataset, split_path)
    counts = dataset["row_counts"]

    synthetic_marker = bool(audit.get("synthetic_fixture")) or allow_synthetic_research
    if not labels_sufficient(audit) and not synthetic_marker:
        payload = _refuse_payload(audit, counts)
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        comparison_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_text(
            json.dumps(
                {
                    "status": "not_selected",
                    "state": "research_blocked",
                    "approved_for_serving": False,
                    "reason": payload["reason"],
                    "comparison_path": str(comparison_path),
                    "recorded_at_utc": payload["recorded_at_utc"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return payload

    train = dataset["train"]
    valid = dataset["validation"]
    if len(train["y"]) < 8 or len(valid["y"]) < 4:
        payload = {
            "status": "refused_insufficient_split_rows",
            "state": "research_blocked",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "row_counts": counts,
            "reason": (
                f"Need enough train/validation labeled rows to compare models "
                f"(train={counts['train']}, validation={counts['validation']})."
            ),
            "publish_probability": False,
            "approved_for_serving": False,
            "synthetic_fixture": synthetic_marker,
        }
        comparison_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload

    comparison = compare_on_validation(
        train["x"],
        train["y"],
        valid["x"],
        valid["y"],
        season_keys_train=train["season_keys"],
        season_keys_valid=valid["season_keys"],
    )
    winner_name = comparison["winner"]["name"]
    threshold = comparison["winner"]["threshold"]
    positive_count = int(np.sum(train["y"] == 1))
    cv_folds = max(2, min(3, positive_count)) if positive_count else 2
    models = build_classifiers(random_state=0, cv_folds=cv_folds)
    winner_model = models[winner_name]
    # Refit winner on train only (preprocessing already train-fit via imputer).
    winner_model.fit(train["x"], train["y"])

    model_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = (
        "philippines_onset_synthetic_winner.joblib"
        if synthetic_marker
        else "philippines_onset_winner.joblib"
    )
    artifact_path = model_dir / artifact_name
    joblib.dump(
        {
            "model": winner_model,
            "feature_names": FEATURE_NAMES,
            "imputer": dataset["imputer"],
            "threshold": threshold,
            "winner_name": winner_name,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "synthetic_fixture": synthetic_marker,
        },
        artifact_path,
    )

    recorded = datetime.now(timezone.utc).isoformat()
    payload = {
        "status": "research_trained",
        "state": "research_trained",
        "recorded_at_utc": recorded,
        "target": TARGET_DEFINITION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "row_counts": counts,
        "import_summary": dataset["import_summary"],
        "baseline": comparison["baseline"],
        "classifiers": comparison["classifiers"],
        "winner": comparison["winner"],
        "model_artifact": str(artifact_path),
        "publish_probability": False,
        "approved_for_serving": False,
        "synthetic_fixture": synthetic_marker,
        "note": (
            "Research training complete. Holdout evaluation and serving approval "
            "are separate states. Synthetic fixtures never approve production serving."
            if synthetic_marker
            else "Research training complete. Run evaluate_philippines_onset next."
        ),
        "harmonization_model_untouched": True,
    }
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison_path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(
        json.dumps(
            {
                "status": "selected",
                "state": "research_trained",
                "chosen_model": winner_name,
                "threshold": threshold,
                "model_artifact": str(artifact_path),
                "comparison_path": str(comparison_path),
                "approved_for_serving": False,
                "synthetic_fixture": synthetic_marker,
                "recorded_at_utc": recorded,
                "why": comparison["winner"]["why"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def _json_default(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-dir", type=Path, default=DATA_DIR / "labels" / "philippines_onset")
    parser.add_argument("--comparison-out", type=Path, default=COMPARISON_PATH)
    parser.add_argument("--selection-out", type=Path, default=SELECTION_PATH)
    parser.add_argument("--split-out", type=Path, default=SPLIT_PATH)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument(
        "--allow-synthetic-research",
        action="store_true",
        help="Permit research training on a clearly marked synthetic label directory.",
    )
    args = parser.parse_args()
    payload = run(
        label_dir=args.label_dir,
        comparison_path=args.comparison_out,
        selection_path=args.selection_out,
        split_path=args.split_out,
        model_dir=args.model_dir,
        audit_path=args.audit,
        allow_synthetic_research=args.allow_synthetic_research,
    )
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "state": payload.get("state"),
                "row_counts": payload.get("row_counts"),
                "winner": None if not payload.get("winner") else payload["winner"].get("name"),
                "approved_for_serving": payload.get("approved_for_serving"),
                "synthetic_fixture": payload.get("synthetic_fixture"),
                "comparison": str(args.comparison_out),
                "selection": str(args.selection_out),
                "reason": payload.get("reason"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
