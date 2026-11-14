"""Upsert Mindanao activity_cell_days from fire-mask coverage + FIRMS heat.

Does not invent weekly activity estimates from hotspot-forecast model scores.
Fills store rows so coverage-backed square-days are less often “no estimate”
when overlays look for activity_cell_days.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.grid import cell_identifier, indices
from vela.hotspot_coverage import COVERAGE_PATH
from vela.hotspot_forecast_dataset import study_cells
from vela.observation_store import ObservationStore, _connect
from vela.settings import DATA_DIR


def main() -> None:
    if not COVERAGE_PATH.is_file():
        raise SystemExit(f"Missing coverage parquet: {COVERAGE_PATH}")
    cells = set(study_cells())
    frame = pd.read_parquet(COVERAGE_PATH)
    store = ObservationStore()
    heat: set[tuple[str, str]] = set()
    with _connect(store.path) as connection:
        rows = connection.execute("SELECT lat, lon, ph_date FROM detections").fetchall()
    for row in rows:
        try:
            lon = float(row["lon"])
            lat = float(row["lat"])
            day = str(row["ph_date"])[:10]
        except (KeyError, TypeError, ValueError):
            continue
        xi, yi = indices(lon, lat)
        cid = cell_identifier(xi, yi)
        if cid in cells:
            heat.add((cid, day))

    upserts = []
    for row in frame.itertuples():
        cid = str(row.cell_id)
        if cid not in cells:
            continue
        day = str(row.ph_date)[:10]
        support = getattr(row, "label_support", None) or ""
        status = getattr(row, "coverage_status", None) or ""
        if support not in {"negative_supported", "positive_candidate"} and status not in {
            "ok_clear_zero",
            "ok_with_heat",
        }:
            continue
        has_heat = (cid, day) in heat or support == "positive_candidate" or status == "ok_with_heat"
        upserts.append(
            {
                "cell_id": cid,
                "ph_date": day,
                "activity_value": 1.0 if has_heat else 0.0,
                "platform": getattr(row, "platform", None) or "coverage",
                "method": "mindanao_coverage_firms_backfill_v1",
                "coverage_status": "usable",
                "model_version": None,
                "numerator": 1.0 if has_heat else 0.0,
                "denominator": 1.0,
            }
        )
    written = store.upsert_activity_rows(upserts)
    out = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "study_cells": len(cells),
        "coverage_rows_considered": int(len(frame)),
        "upserts": len(upserts),
        "written": written,
        "heat_cell_days_in_store": len(heat),
        "note": (
            "Store activity_cell_days from measured coverage + FIRMS heat only. "
            "Not a wildfire probability and not a hotspot-forecast percentage."
        ),
    }
    path = DATA_DIR / "metrics" / "mindanao_activity_coverage_backfill.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
