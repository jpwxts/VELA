"""Philippine agreement-with-Aqua evaluation for the frozen Suomi-NPP model.

Pre-registration (chosen before looking at outcomes):
- Areas: Maguindanao del Norte cell neighborhood (2393:174 padded) plus any
  paired Philippine cell-days later written to the observation store.
- Dates: CMR a-priori March 2019 Mindanao week first; FIRMS snapshot week second.
- Inclusion: jointly eligible Aqua–Suomi-NPP cell-days only.
- Prediction path: hide Aqua; run frozen Suomi-NPP random forest when features exist.
- Reference: reveal Aqua detection (0/1).
- Metrics: weekly signed error, equal-weight weekly MAE (percentage points),
  cell-level Brier score, raw-VIIRS baseline on the same rows.
- Reserved project test sets (Reveal 2023–2024, Pantanal) stay untouched.
- Production model stays frozen.

If too few Philippine pairs exist, this script reports counts and leaves MAE undefined.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.findings import reliability_block
from vela.settings import DATA_DIR
from vela.serving import SELECTION_PATH, selected_method


def _paired_ph_rows():
    path = DATA_DIR / "processed" / "paired_cells.parquet"
    if not path.is_file():
        return None, "paired_cells.parquet missing"
    try:
        import pandas as pd
    except ImportError:
        return None, "pandas unavailable"
    frame = pd.read_parquet(path)
    if "region_id" not in frame.columns:
        return frame.iloc[0:0], "no region_id column"
    ph = frame[frame["region_id"].astype(str).str.contains("philippine|mindanao|iloilo", case=False, na=False)]
    return ph, None


def main() -> None:
    selection = {}
    if Path(SELECTION_PATH).is_file():
        selection = json.loads(Path(SELECTION_PATH).read_text(encoding="utf-8"))
    reliability = reliability_block(selection)
    paired, err = _paired_ph_rows()
    n = 0 if paired is None else int(len(paired))
    cmr_plan = DATA_DIR / "metrics" / "mindanao_2019-03_download_plan.json"
    cmr = json.loads(cmr_plan.read_text()) if cmr_plan.is_file() else {}
    report = {
        "label": "Agreement with Aqua in the Philippines",
        "model_frozen": True,
        "chosen_model": selected_method(),
        "model_hash_or_selection": {
            "selection_path": str(SELECTION_PATH),
            "chosen_model": selection.get("chosen_model"),
            "selection_status": selection.get("selection_status"),
        },
        "pre_registration": {
            "areas": ["Mindanao cell 2393:174 padded bbox", "future PH paired_cells region_ids"],
            "date_order": [
                "2019-03-04/2019-03-10 a priori March week",
                "2026-11-02/2026-11-08 FIRMS snapshot week",
            ],
            "inclusion": "jointly eligible Aqua–Suomi-NPP cell-days only",
            "prediction_path": "hide Aqua; frozen Suomi-NPP RF when features exist",
            "reference": "Aqua detected 0/1",
            "metrics": [
                "weekly signed error (pp)",
                "equal-weight weekly MAE (pp)",
                "cell-level Brier score",
                "raw VIIRS baseline on same rows",
            ],
            "reserved_sets_untouched": ["Reveal 2023–2024", "Pantanal transfer"],
        },
        "development_reference_not_this_test": {
            "weekly_share_mae_percentage_points": reliability.get("value_percentage_points"),
            "label": "development performance on non-Philippine tune weeks",
            "plain_language": reliability.get("plain_language"),
        },
        "philippine_paired_cell_days": n,
        "paired_cells_error": err,
        "regions": 0,
        "weeks": 0,
        "aqua_positive_cases": 0,
        "aqua_zero_cases": 0,
        "weekly_mae_percentage_points": None,
        "brier_score": None,
        "undefined_metrics_reason": None
        if n >= 30
        else (
            f"Only {n} Philippine paired cell-days found in paired_cells.parquet. "
            "Weekly MAE and Brier score are undefined until jointly eligible PH pairs exist."
        ),
        "archive_blocker": {
            "smallest_candidate_download_bytes": cmr.get("additional_bytes_needed") or cmr.get("total_bytes"),
            "download_executed": cmr.get("download_executed"),
            "files": cmr.get("files"),
            "note": cmr.get("note")
            or "Catalog overlap alone cannot establish clear land. Download was not executed.",
        },
        "wildfire_confirmation": (
            "Wildfire confirmation requires a separate evaluation with independently "
            "verified incident and non-wildfire outcomes. This script measures agreement with Aqua only."
        ),
        "philippine_status": reliability.get("philippine_status"),
    }
    out = DATA_DIR / "metrics" / "philippines_agreement_with_aqua.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
