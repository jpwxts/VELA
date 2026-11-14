"""Stage-by-stage Mindanao activity denominator diagnosis.

Reports where the count drops to zero for one small Maguindanao polygon and the
a-priori March 2019 week. Does not download granules.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.findings import model_for_drawn_area
from vela.serving import build_calendar, region_label
from vela.settings import DATA_DIR

# Maguindanao del Norte cell 2393:174 neighborhood (small drawn land).
WEST, SOUTH, EAST, NORTH = 124.00, 6.82, 124.10, 6.90
WEEK = "2019-03-04/2019-03-10"
YEAR = 2019


def _cmr_counts() -> dict:
    hist = DATA_DIR / "metrics" / "mindanao_cmr_historical_windows.json"
    plan = DATA_DIR / "metrics" / "mindanao_2019-03_download_plan.json"
    out = {"historical_window": None, "download_plan": None}
    if hist.is_file():
        payload = json.loads(hist.read_text(encoding="utf-8"))
        for window in payload.get("windows") or []:
            temporal = window.get("temporal") or {}
            blob = " ".join(
                [
                    str(window.get("label") or ""),
                    str(temporal.get("start") or ""),
                    str(temporal.get("end") or ""),
                ]
            )
            if "2019-03" in blob or "March 2019" in blob:
                out["historical_window"] = {
                    "label": window.get("label"),
                    "products": window.get("products"),
                    "shared_utc_days": window.get("shared_utc_days"),
                    "same_day_aqua_viirs_possible": window.get("same_day_aqua_viirs_possible"),
                }
                break
    if plan.is_file():
        out["download_plan"] = json.loads(plan.read_text(encoding="utf-8"))
    return out


def _paired_ph_counts() -> dict:
    path = DATA_DIR / "processed" / "paired_cells.parquet"
    if not path.is_file():
        return {"path": str(path), "exists": False, "rows": 0, "ph_rows": 0, "bbox_rows": 0}
    import pandas as pd

    frame = pd.read_parquet(path)
    ph = frame
    if "region_id" in frame.columns:
        ph = frame[frame["region_id"].astype(str).str.contains("philippine|mindanao|iloilo", case=False, na=False)]
    bbox_rows = 0
    if {"lon", "lat"}.issubset(frame.columns):
        bbox = frame[
            (frame["lon"] >= WEST)
            & (frame["lon"] <= EAST)
            & (frame["lat"] >= SOUTH)
            & (frame["lat"] <= NORTH)
        ]
        bbox_rows = int(len(bbox))
    elif "cell_id" in frame.columns:
        bbox_rows = int((frame["cell_id"].astype(str) == "2393:174").sum())
    return {
        "path": str(path),
        "exists": True,
        "rows": int(len(frame)),
        "ph_rows": int(len(ph)),
        "bbox_rows": bbox_rows,
    }


def main() -> None:
    cmr = _cmr_counts()
    paired = _paired_ph_counts()
    label = region_label(WEST, SOUTH, EAST, NORTH)
    calendar = build_calendar(WEST, SOUTH, EAST, NORTH, YEAR)
    week = None
    for item in calendar.get("weeks") or []:
        if item.get("week_start") == "2019-03-04":
            week = item
            break
    activity = model_for_drawn_area(WEST, SOUTH, EAST, NORTH, "2019-03-06")

    granules_found = None
    if cmr.get("historical_window"):
        products = cmr["historical_window"].get("products") or {}
        granules_found = {name: (row or {}).get("count") for name, row in products.items()}

    stages = [
        {
            "stage": "1_cmr_catalog_granules",
            "count": None if granules_found is None else sum(int(v or 0) for v in granules_found.values()),
            "detail": granules_found,
            "note": "Catalog footprint matches only; clear land not established.",
        },
        {
            "stage": "2_land_intersecting_processed_rows",
            "count": paired["bbox_rows"],
            "detail": paired,
            "note": "Processed paired_cells rows whose cell falls in the Maguindanao polygon.",
        },
        {
            "stage": "3_usable_aqua_coverage_cell_days",
            "count": 0 if week is None else int((week.get("method_counts") or {}).get("observed Aqua activity") or 0),
            "detail": None if week is None else week.get("method_counts"),
        },
        {
            "stage": "4_eligible_suomi_npp_fallback_inputs",
            "count": 0 if week is None else int((week.get("method_counts") or {}).get("calibrated VIIRS estimate") or 0),
            "detail": {
                "raw_viirs": None if week is None else (week.get("method_counts") or {}).get("raw VIIRS activity"),
                "unavailable_calibration_pending": None
                if week is None
                else (week.get("method_counts") or {}).get("unavailable"),
            },
        },
        {
            "stage": "5_history_contributions_denominator",
            "count": None if week is None else week.get("activity_denominator"),
            "detail": {
                "activity_rate": None if week is None else week.get("activity_rate"),
                "activity_status": None if week is None else week.get("activity_status"),
                "held_out": None if week is None else week.get("held_out"),
                "region_label": label,
                "model_for_drawn_area": {
                    "status": activity.get("status"),
                    "activity_rate": activity.get("activity_rate"),
                    "activity_denominator": activity.get("activity_denominator"),
                    "explanation": activity.get("explanation"),
                },
            },
        },
    ]
    first_zero = next(
        (
            row["stage"]
            for row in stages
            if row["count"] is None or int(row["count"] or 0) == 0
        ),
        None,
    )
    # Prefer the first *processed* zero when catalog granules exist.
    if granules_found and any(int(v or 0) > 0 for v in granules_found.values()):
        first_zero = next(
            (
                row["stage"]
                for row in stages
                if row["stage"] != "1_cmr_catalog_granules"
                and (row["count"] is None or int(row["count"] or 0) == 0)
            ),
            first_zero,
        )
    report = {
        "polygon": {"west": WEST, "south": SOUTH, "east": EAST, "north": NORTH},
        "week": WEEK,
        "serving_rule_note": (
            "Contribution selection does not require jointly eligible Aqua–Suomi pairs: "
            "Aqua alone can supply an observed contribution; eligible Suomi-NPP can supply a "
            "calibrated fallback when Aqua is missing. Joint pairs are required only for the "
            "separate Agreement-with-Aqua accuracy comparison. Ingest still needs fire+geo "
            "granules per platform before any paired_cells rows exist."
        ),
        "cmr": cmr,
        "stages": stages,
        "first_stage_that_drops_to_zero": first_zero,
        "download_required": paired["bbox_rows"] == 0,
        "smallest_viable_download_bytes": (cmr.get("download_plan") or {}).get("total_bytes"),
        "download_executed": (cmr.get("download_plan") or {}).get("download_executed"),
    }
    out = DATA_DIR / "metrics" / "mindanao_denominator_diagnosis.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
