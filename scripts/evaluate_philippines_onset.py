"""Evaluate a selected Philippine onset model on the untouched holdout.

Distinct states:
  research_trained → holdout_evaluated → approved_for_serving (manual / separate)

Never scores the harmonization model as an onset forecast. Synthetic fixtures
are scored for plumbing only and never approve production serving.
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

from vela.onset_dataset import build_dataset
from vela.onset_forecast import (
    SELECTION_PATH,
    SPLIT_PATH,
    labels_sufficient,
    load_audit,
    load_selection,
)
from vela.onset_models import classification_report_block, predict_proba_positive, seasonal_baseline_probs
from vela.settings import DATA_DIR

OUT = DATA_DIR / "metrics" / "philippines_onset_holdout_evaluation.json"


def _json_default(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value))


def run(
    *,
    label_dir: Path,
    selection_path: Path,
    split_path: Path,
    out_path: Path,
    audit_path: Path | None = None,
) -> dict:
    audit = load_audit(audit_path) if audit_path else load_audit()
    selection = json.loads(selection_path.read_text(encoding="utf-8")) if selection_path.is_file() else None
    dataset = build_dataset(label_dir, split_path=split_path)
    test = dataset["test"]
    payload = {
        "label": "Philippine onset holdout evaluation",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "labels_sufficient": labels_sufficient(audit),
        "selection": selection,
        "row_counts": dataset["row_counts"],
        "holdout_rows": int(len(test["y"])),
        "metrics": None,
        "status": "not_run",
        "state": "not_run",
        "approved_for_serving": False,
        "harmonization_model_excluded": True,
        "synthetic_fixture": bool((selection or {}).get("synthetic_fixture") or audit.get("synthetic_fixture")),
    }
    if selection is None or selection.get("status") != "selected":
        payload["status"] = "blocked_no_selected_model"
        payload["state"] = "blocked_no_selected_model"
        payload["reason"] = "No frozen onset model selection is present."
    elif len(test["y"]) == 0:
        payload["status"] = "blocked_holdout_empty"
        payload["state"] = "blocked_holdout_empty"
        payload["reason"] = "Holdout split has zero labeled rows."
    else:
        artifact = Path(selection["model_artifact"])
        bundle = joblib.load(artifact)
        model = bundle["model"]
        threshold = float(bundle.get("threshold") or selection.get("threshold") or 0.5)
        y_prob = predict_proba_positive(model, test["x"])
        baseline = seasonal_baseline_probs(
            dataset["train"]["y"],
            dataset["train"]["season_keys"],
            test["season_keys"],
        )
        metrics = classification_report_block(
            test["y"], y_prob, threshold=threshold, baseline_prob=baseline
        )
        payload.update(
            {
                "status": "holdout_evaluated",
                "state": "holdout_evaluated",
                "metrics": metrics,
                "holdout_positive_count": int(np.sum(test["y"] == 1)),
                "holdout_negative_count": int(np.sum(test["y"] == 0)),
                "model_artifact": str(artifact),
                "approved_for_serving": False,
                "reason": (
                    "Holdout scored for research. Synthetic fixtures remain isolated from "
                    "production forecasts and accuracy claims."
                    if payload["synthetic_fixture"]
                    else (
                        "Holdout scored. Serving approval remains a separate decision "
                        "after reviewing metrics and label provenance."
                    )
                ),
            }
        )
        # Keep selection state advanced but not serving-approved.
        selection = dict(selection)
        selection["state"] = "holdout_evaluated"
        selection["holdout_evaluation_path"] = str(out_path)
        selection["approved_for_serving"] = False
        selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
        payload["selection"] = selection

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-dir", type=Path, default=DATA_DIR / "labels" / "philippines_onset")
    parser.add_argument("--selection", type=Path, default=SELECTION_PATH)
    parser.add_argument("--split", type=Path, default=SPLIT_PATH)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--audit", type=Path, default=None)
    args = parser.parse_args()
    payload = run(
        label_dir=args.label_dir,
        selection_path=args.selection,
        split_path=args.split,
        out_path=args.out,
        audit_path=args.audit,
    )
    print(
        json.dumps(
            {
                "path": str(args.out),
                "status": payload.get("status"),
                "state": payload.get("state"),
                "holdout_rows": payload.get("holdout_rows"),
                "metrics": payload.get("metrics"),
                "approved_for_serving": payload.get("approved_for_serving"),
                "synthetic_fixture": payload.get("synthetic_fixture"),
                "reason": payload.get("reason"),
            },
            indent=2,
            default=_json_default,
        )
    )


if __name__ == "__main__":
    main()
