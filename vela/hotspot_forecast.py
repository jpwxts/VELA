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
# Frozen after 11f1861 audit: empty FIRMS searches are NOT clear-sky coverage.
COVERAGE_RULE = {
    "version": "hotspot_coverage_v2",
    "platforms": ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"],
    "products": (
        "Labels: FIRMS detections for positives; fire-mask + geolocation "
        "(MYD14/MYD03, VNP14IMG/VNP03IMG, VJ1/VJ2) for usable clear coverage / negatives. "
        "FIRMS area CSV alone never establishes a clear zero."
    ),
    "detection_quality_filters": (
        "All FIRMS points returned for the platforms above are qualifying positives. "
        "No confidence/FRP filter in v2 (frozen before model comparison)."
    ),
    "positive": (
        "≥1 qualifying FIRMS detection whose acquisition falls inside the square and "
        "the [00:00, +24h) Asia/Manila window. Multiple pixels/passes/satellites → one positive."
    ),
    "negative": (
        "Measured usable fire-mask/geolocation coverage for that square-day "
        "(visible land meets Vela’s ≥50% cell coverage rule on at least one MODIS/VIIRS "
        "platform pass) AND zero qualifying detections in the square-window."
    ),
    "unknown": (
        "No usable fire-mask/geolocation coverage for the square-day, OR incomplete retrieval. "
        "A successful FIRMS search that returns zero detections is insufficient evidence of "
        "clear coverage and is labeled unknown — never negative."
    ),
    "availability_assumption": (
        "Historical FIRMS publication timestamps are unavailable. Default research rule: "
        "treat acquisition time as availability time (acq≈avail). Predictors use only "
        "detections with acquisition < issue time. Target-window detections are labels only. "
        "A conservative publication-delay sensitivity (6h / 24h) is reported separately."
    ),
    "supersedes": "hotspot_coverage_v1",
    "v1_defect": (
        "v1 treated regional FIRMS query ok/ok_zero (≥2 platforms) as adequate coverage "
        "for negatives. Audit of 11f1861: 62,749 negatives and 0 unknowns were inferred "
        "from empty searches without fire-mask evidence."
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
COMPARISON_V1_ARCHIVE = (
    DATA_DIR / "metrics" / "philippines_hotspot_model_comparison_v1_flawed_negatives.json"
)
DATASET_PATH = DATA_DIR / "processed" / "philippines_hotspot_cell_days.parquet"
RULES_PATH = DATA_DIR / "metrics" / "philippines_hotspot_coverage_rules.json"
INVENTORY_PATH = DATA_DIR / "metrics" / "philippines_hotspot_inventory.json"
AUDIT_PATH = DATA_DIR / "metrics" / "philippines_hotspot_coverage_audit.json"
PAIRED_CELLS_PATH = DATA_DIR / "processed" / "paired_cells.parquet"


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
    if not sel:
        return (
            "No Philippine hotspot-forecast model is selected yet. "
            "Usable fire-mask/geolocation negatives are required after the coverage v2 audit."
        )
    if sel.get("approved_for_serving") is not True or sel.get("status") != "selected":
        detail = sel.get("reason") or COVERAGE_RULE["v1_defect"]
        return (
            f"Chance of satellite-detected heat is not published "
            f"(state={sel.get('state') or sel.get('status')}). {detail}"
        )
    return ""
