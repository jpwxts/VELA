"""Philippine satellite-hotspot 24-hour forecast (MODIS/VIIRS only).

Question: For this 5 km square, what is the estimated chance that MODIS or VIIRS
will detect heat in the next 24 hours?

Public label: “Chance of satellite-detected heat.”
Distinct from Aqua–Suomi harmonization and Philippine wildfire-onset research.
No BFP records or weather APIs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vela.settings import DATA_DIR, ROOT

MANILA = ZoneInfo("Asia/Manila")
PRODUCT = "philippines_hotspot_24h"
FEATURE_SCHEMA_VERSION = "hotspot_features_v1"
STUDY = {
    "id": "mindanao_maguindanao_compact_v1",
    "label": "Compact Maguindanao / western Mindanao study box",
    "bbox": {"west": 123.6, "south": 6.3, "east": 124.7, "north": 7.4},
    "clip_preset": "mindanao",
}
COVERAGE_RULE = {
    "version": "hotspot_coverage_v1",
    "platforms": ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"],
    "products": "FIRMS area CSV via FirmsClient (MODIS_SP/NRT, VIIRS_*_SP/NRT)",
    "detection_quality_filters": (
        "All FIRMS points returned for the platforms above are qualifying. "
        "No confidence/FRP filter in v1 (frozen before model comparison)."
    ),
    "positive": (
        "≥1 qualifying detection whose Philippine-local acquisition falls inside "
        "the square and the [00:00, +24h) Manila window."
    ),
    "negative": (
        "regional_query_ok for the study bbox on that Philippine day "
        "(≥2 platforms status in {ok, no_hotspots}) AND zero qualifying detections "
        "in the square-window. This is successful FIRMS retrieval including zeros, "
        "not a per-pixel clear-sky proof."
    ),
    "unknown": "Day not queried successfully, or fewer than 2 platform successes.",
    "availability_assumption": (
        "Historical publication timestamps are unavailable. Conservative rule: "
        "treat acquisition time as availability time. Predictors use only detections "
        "with acquisition < issue time. Target-window detections are labels only."
    ),
}
FEATURE_NAMES = [
    "heat_detections_1d",
    "heat_detections_3d",
    "heat_detections_7d",
    "neighbor_heat_1d",
    "neighbor_heat_3d",
    "hours_since_last_detection",
    "hours_since_last_usable_pass",
    "coverage_days_7d",
    "distinct_satellites_7d",
    "persistence_heat_yesterday",
    "month_sin",
    "month_cos",
]

SPLIT_PATH = DATA_DIR / "manifests" / "philippines_hotspot_split.json"
SELECTION_PATH = DATA_DIR / "models" / "philippines_hotspot_selection.json"
COMPARISON_PATH = DATA_DIR / "metrics" / "philippines_hotspot_model_comparison.json"
DATASET_PATH = DATA_DIR / "processed" / "philippines_hotspot_cell_days.parquet"
RULES_PATH = DATA_DIR / "metrics" / "philippines_hotspot_coverage_rules.json"
INVENTORY_PATH = DATA_DIR / "metrics" / "philippines_hotspot_inventory.json"


def issue_datetime_manila(issue_date: date | str) -> datetime:
    day = date.fromisoformat(str(issue_date)[:10])
    return datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=MANILA)


def valid_interval(issue_date: date | str) -> dict[str, str]:
    start = issue_datetime_manila(issue_date)
    end = start + timedelta(days=1)
    return {
        "start_manila": start.isoformat(),
        "end_manila": end.isoformat(),
        "start_utc": start.astimezone(timezone.utc).isoformat(),
        "end_utc": end.astimezone(timezone.utc).isoformat(),
    }


def freeze_rules(path: Path | None = None) -> dict[str, Any]:
    payload = {
        "product": PRODUCT,
        "question": (
            "For this 5 km square, what is the estimated chance that MODIS or VIIRS "
            "will detect heat in the next 24 hours?"
        ),
        "public_label": "Chance of satellite-detected heat",
        "study": STUDY,
        "coverage_rule": COVERAGE_RULE,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "harmonization_untouched": True,
        "onset_pipeline_untouched": True,
        "excludes": ["BFP", "weather APIs", "harmonization probability", "onset probability"],
    }
    target = path or RULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_selection() -> dict | None:
    if not SELECTION_PATH.is_file():
        return None
    return json.loads(SELECTION_PATH.read_text(encoding="utf-8"))


def model_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def forecast_unavailable_reason(selection: dict | None = None) -> str:
    sel = selection if selection is not None else load_selection()
    if not sel or sel.get("status") != "selected":
        return (
            "No Philippine hotspot-forecast model is selected yet. "
            "Run scripts/train_hotspot_forecast.py after the dataset build."
        )
    if sel.get("approved_for_serving") is not True:
        return (
            f"Research model selected ({sel.get('chosen_model')}) but serving is not approved "
            f"(state={sel.get('state')})."
        )
    return ""
