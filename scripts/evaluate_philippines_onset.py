"""Evaluate a selected Philippine onset model on the untouched holdout.

Refuses when no model is selected or labels remain insufficient. Never scores
the harmonization model as an onset forecast.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.onset_forecast import SELECTION_PATH, labels_sufficient, load_audit, load_selection, load_split
from vela.settings import DATA_DIR

OUT = DATA_DIR / "metrics" / "philippines_onset_holdout_evaluation.json"


def main() -> None:
    audit = load_audit()
    split = load_split()
    selection = load_selection()
    payload = {
        "label": "Philippine onset holdout evaluation",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "labels_sufficient": labels_sufficient(audit),
        "selection": selection,
        "split_test_rule": (split.get("temporal_holdout") or {}),
        "metrics": None,
        "status": "not_run",
        "harmonization_model_excluded": True,
    }
    if not labels_sufficient(audit):
        payload["status"] = "blocked_insufficient_labels"
        payload["reason"] = audit.get("publish_blocker")
    elif not selection or selection.get("status") != "selected":
        payload["status"] = "blocked_no_selected_model"
        payload["reason"] = "No frozen onset model selection is present."
    else:
        payload["status"] = "ready_but_holdout_empty"
        payload["reason"] = (
            "A selected model exists, but the holdout currently has zero labeled "
            "rows in the split manifest."
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT.relative_to(ROOT)), **{k: payload[k] for k in ("status", "reason") if k in payload}}, indent=2))


if __name__ == "__main__":
    main()
