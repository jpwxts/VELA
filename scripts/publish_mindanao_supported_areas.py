"""Publish Mindanao island + tile supported-area map (evaluated vs inventory-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.hotspot_forecast import MAGUINDANAO_EVALUATED, STUDY
from vela.hotspot_forecast_dataset import evaluated_cells, study_cells
from vela.settings import DATA_DIR


def _bbox_feature(region_id: str, label: str, bbox: dict, evaluated: bool) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": region_id, "label": label, "evaluated": evaluated},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [bbox["west"], bbox["south"]],
                    [bbox["east"], bbox["south"]],
                    [bbox["east"], bbox["north"]],
                    [bbox["west"], bbox["north"]],
                    [bbox["west"], bbox["south"]],
                ]
            ],
        },
    }


def main() -> None:
    registry = json.loads(
        (DATA_DIR / "manifests" / "mindanao_hotspot_regions_v1.json").read_text(encoding="utf-8")
    )
    island_cells = len(study_cells())
    eval_cells = len(evaluated_cells())
    regions = [
        {
            "id": "mindanao_island_v1",
            "label": STUDY["label"],
            "bbox": STUDY["bbox"],
            "role": "serving_geography",
            "n_land_cells": island_cells,
            "evaluated": False,
            "metrics_ref": None,
            "serving": "readings_weather_coverage_status",
            "geojson": _bbox_feature("mindanao_island_v1", STUDY["label"], STUDY["bbox"], False),
        },
        {
            "id": "maguindanao_compact_v1",
            "label": MAGUINDANAO_EVALUATED["label"],
            "bbox": MAGUINDANAO_EVALUATED["bbox"],
            "role": "control_existing_v2_1_serving",
            "overwrite_v2_1_selection": False,
            "n_land_cells": eval_cells,
            "evaluated": True,
            "metrics_ref": "data/metrics/philippines_hotspot_model_comparison.json",
            "demo_cell": "2398:168",
            "serving": "active_v2_1_percentages",
            "geojson": _bbox_feature(
                "maguindanao_compact_v1", MAGUINDANAO_EVALUATED["label"], MAGUINDANAO_EVALUATED["bbox"], True
            ),
        },
    ]
    for row in registry.get("regions") or []:
        if row["id"] in {"maguindanao_compact_v1"}:
            continue
        regions.append(
            {
                **row,
                "evaluated": False,
                "metrics_ref": None,
                "serving": "inventory_or_coverage_batch",
                "geojson": _bbox_feature(row["id"], row.get("label") or row["id"], row["bbox"], False),
            }
        )
    payload = {
        "title": "Mindanao hotspot forecast supported areas",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ph_clock_reference": datetime.now(timezone.utc).date().isoformat(),
        "study": STUDY,
        "percentage_zone": MAGUINDANAO_EVALUATED,
        "regions": regions,
        "serving_rule": (
            "Study geography is all Mindanao land. Serve Maguindanao v2.1 percentages only inside "
            "maguindanao_compact_v1. Elsewhere in Mindanao: FIRMS readings + weather + coverage status. "
            "Outside Mindanao: unsupported for hotspot percentages."
        ),
        "multi_region_comparison": "data/metrics/mindanao_hotspot_multi_region_comparison.json",
        "inventory": "data/metrics/mindanao_hotspot_multi_region_inventory.json",
        "island_selection": "data/models/philippines_hotspot_models/mindanao_island_selection.json",
    }
    out = DATA_DIR / "metrics" / "mindanao_hotspot_supported_areas.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"regions": len(regions), "path": str(out), "island_cells": island_cells}, indent=2))


if __name__ == "__main__":
    main()
