"""Train and compare six onset classifiers fairly (Mindanao-first).

Models:
  1. Logistic regression
  2. Decision tree
  3. Random forest
  4. Extra Trees
  5. Histogram gradient boosting
  6. Calibrated support vector machine
Plus a regional seasonal event-rate baseline.

Selection uses validation Brier score relative to the seasonal baseline and
calibration quality. Alert thresholds are chosen on validation only. The
holdout is evaluated once after selection.

Refuses to fit or publish when the label audit shows insufficient verified
onset labels / reporting coverage.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.onset_forecast import (
    AUDIT_PATH,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    SELECTION_PATH,
    SPLIT_PATH,
    TARGET_DEFINITION,
    labels_sufficient,
    load_audit,
    load_split,
)
from vela.settings import DATA_DIR

COMPARISON_PATH = DATA_DIR / "metrics" / "philippines_onset_model_comparison.json"


def _refuse_payload(audit: dict, split: dict) -> dict:
    return {
        "status": "refused_insufficient_labels",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": TARGET_DEFINITION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "split_manifest": str(SPLIT_PATH.relative_to(ROOT)),
        "split_status": split.get("status"),
        "split_row_counts": split.get("row_counts"),
        "audit_path": str(AUDIT_PATH.relative_to(ROOT)),
        "usable_unique_wildfire_starts": audit.get("usable_unique_wildfire_starts"),
        "square_days_with_credible_reporting_coverage": audit.get(
            "square_days_with_credible_reporting_coverage"
        ),
        "negatives_supported": audit.get("negatives_supported"),
        "classifiers_prepared": [
            "logistic_regression",
            "decision_tree",
            "random_forest",
            "extra_trees",
            "hist_gradient_boosting",
            "calibrated_svm",
            "regional_seasonal_event_rate_baseline",
        ],
        "selection_rule": (
            "Choose on validation by Brier score relative to the seasonal baseline "
            "and calibration; report PR/F1/accuracy/confusion on the same cases. "
            "Do not choose by how close accuracy is to F1. Evaluate the winner once "
            "on the untouched holdout."
        ),
        "tuning_budget": (
            "Resource-conscious: ≤ 24 validation trials per classifier family on "
            "laptop-class hardware; no GPU required."
        ),
        "winner": None,
        "holdout_evaluation": None,
        "publish_probability": False,
        "reason": audit.get("publish_blocker"),
        "next_runnable_step": audit.get("next_runnable_step"),
        "harmonization_model_untouched": True,
    }


def run(force: bool = False) -> dict:
    audit = load_audit()
    split = load_split()
    if not labels_sufficient(audit) and not force:
        payload = _refuse_payload(audit, split)
        COMPARISON_PATH.parent.mkdir(parents=True, exist_ok=True)
        COMPARISON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        SELECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
        SELECTION_PATH.write_text(
            json.dumps(
                {
                    "status": "not_selected",
                    "reason": payload["reason"],
                    "comparison_path": str(COMPARISON_PATH.relative_to(ROOT)),
                    "recorded_at_utc": payload["recorded_at_utc"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return payload

    # Label-backed training path (activated when audit becomes sufficient).
    raise RuntimeError(
        "Label-backed training is prepared but not executed in this environment: "
        "wire the loaded onset table to the six classifiers only after "
        "scripts/audit_philippines_onset_labels.py reports usable starts and "
        "credible negative coverage."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force-train-without-labels",
        action="store_true",
        help="Disabled path retained for explicit opt-in later; still refuses by default.",
    )
    args = parser.parse_args()
    payload = run(force=False if not args.force_train_without_labels else False)
    print(json.dumps({
        "status": payload["status"],
        "comparison": str(COMPARISON_PATH.relative_to(ROOT)),
        "selection": str(SELECTION_PATH.relative_to(ROOT)),
        "publish_probability": payload.get("publish_probability"),
        "reason": payload.get("reason"),
        "next_runnable_step": payload.get("next_runnable_step"),
    }, indent=2))


if __name__ == "__main__":
    main()
