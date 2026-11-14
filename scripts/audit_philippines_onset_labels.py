"""Audit Philippine wildfire-onset labels before any onset model training.

Usage:
  python -m scripts.audit_philippines_onset_labels

Writes data/metrics/philippines_onset_label_audit.json. Does not download FOI
attachments or invent geocoded starts.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.settings import DATA_DIR
from vela.wildfire_reports import MISSING_DEPENDENCY, lookup_wildfire_report

OUT = DATA_DIR / "metrics" / "philippines_onset_label_audit.json"
LABEL_DIR = DATA_DIR / "labels" / "philippines_onset"


def _count_local_label_files() -> dict:
    if not LABEL_DIR.is_dir():
        return {"directory_exists": False, "files": [], "usable_rows": 0}
    files = sorted(
        str(path.relative_to(ROOT))
        for path in LABEL_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".csv", ".json", ".geojson", ".parquet"}
    )
    return {"directory_exists": True, "files": files, "usable_rows": 0}


def build_audit() -> dict:
    sample = lookup_wildfire_report(
        west=124.03,
        south=6.83,
        east=124.09,
        north=6.89,
        date="2026-11-07",
        cell_id="2393:174",
    )
    local = _count_local_label_files()
    sources = [
        {
            "name": "Vela configured wildfire-report lookup",
            "path_or_url": "vela/wildfire_reports.py",
            "accessible_now": False,
            "geographic_coverage": "none configured",
            "date_coverage": "none",
            "event_definition": "unavailable",
            "coordinate_precision": "n/a",
            "start_vs_discovery": "n/a",
            "duplicates": "n/a",
            "reporting_completeness": "n/a",
            "distinguishes_ag_burning_structural_ongoing": False,
            "usable_unique_wildfire_starts": 0,
            "notes": sample.get("missing_dependency") or MISSING_DEPENDENCY,
        },
        {
            "name": "Bureau of Fire Protection (BFP) via eFOI",
            "path_or_url": "https://www.foi.gov.ph/agencies/bfp/",
            "accessible_now": False,
            "geographic_coverage": (
                "FOI releases are request-specific (city/province/region). "
                "No open nationwide Mindanao wildfire-onset geocode feed is mounted in Vela."
            ),
            "date_coverage": "varies by FOI request; not loaded here",
            "event_definition": (
                "Often mixed fire incidents (structural, grass, forest). "
                "Forest-fire subsets appear in some FOI replies but are not automatically downloadable."
            ),
            "coordinate_precision": (
                "Frequently address/barangay level; coordinates often require manual geocoding."
            ),
            "start_vs_discovery": (
                "Report time / alarm time is common; true ignition onset is usually unknown."
            ),
            "duplicates": "Unknown without the microdata table",
            "reporting_completeness": (
                "Incomplete for rural wildfires; cannot support square-day negative labels nationwide."
            ),
            "distinguishes_ag_burning_structural_ongoing": False,
            "usable_unique_wildfire_starts": 0,
            "notes": (
                "Example successful FOI pages exist (e.g. Davao City forest-fire request "
                "#BFP-338191405957), but attachments are not in this repository and are not "
                "an open API. Treating as inaccessible for training until a licensed table is filed "
                f"under {LABEL_DIR.relative_to(ROOT)}."
            ),
        },
        {
            "name": "DENR / local DRRM wildfire or forest-fire bulletins",
            "path_or_url": "https://www.denr.gov.ph/",
            "accessible_now": False,
            "geographic_coverage": "irregular public bulletins; not a square-day registry",
            "date_coverage": "event-driven",
            "event_definition": "Forest/grass fire mentions; often narrative",
            "coordinate_precision": "place name / municipality common",
            "start_vs_discovery": "discovery/report oriented",
            "duplicates": "unknown",
            "reporting_completeness": "not adequate for negative training examples",
            "distinguishes_ag_burning_structural_ongoing": False,
            "usable_unique_wildfire_starts": 0,
            "notes": "No machine-readable DENR Mindanao onset extract is present in the repo.",
        },
        {
            "name": "NASA FIRMS / local observation store (satellite heat)",
            "path_or_url": "data/observations/philippines.sqlite + data/public/philippines/",
            "accessible_now": True,
            "geographic_coverage": "Philippines detections (Live + Nov 7 snapshot)",
            "date_coverage": "recent Live days + 2026-11-07 public snapshot",
            "event_definition": "Hot pixel / heat detection — NOT a verified wildfire start",
            "coordinate_precision": "sensor pixel / FIRMS point",
            "start_vs_discovery": "acquisition time of heat, not ignition onset",
            "duplicates": "deduplicated in observation store by platform×time×lat×lon",
            "reporting_completeness": "n/a for agency wildfire confirmation",
            "distinguishes_ag_burning_structural_ongoing": False,
            "usable_unique_wildfire_starts": 0,
            "notes": (
                "Usable as issue-time features (prior heat, pass timing). "
                "Must not be used as positive onset labels or as proof of no wildfire."
            ),
        },
    ]
    audit = {
        "title": "Philippine wildfire-onset label audit (Mindanao-first)",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_label": (
            "New wildfire start in a 5 km square during the next Philippine 24 hours"
        ),
        "stronger_label_warning": (
            "Evidence currently supports at most 'reported fire incident' after an FOI "
            "ingest — not verified ignition onset. Do not publish a forecast under the "
            "stronger onset label until onset time and wildfire class are present."
        ),
        "sources": sources,
        "local_label_directory": local,
        "usable_unique_wildfire_starts": 0,
        "usable_start_dates": [],
        "usable_regions": [],
        "square_days_with_credible_reporting_coverage": 0,
        "negatives_supported": False,
        "uncertain_locations": "all candidate agency sources until geocoded microdata arrives",
        "uncertain_onset_dates": "all candidate agency sources until onset≠discovery is verified",
        "missing_reports": "treated as unknown (not negative)",
        "publish_blocker": (
            "0 usable unique wildfire starts and 0 square-days with credible reporting "
            "coverage. Negatives are not supported. Vela will not publish an onset percentage."
        ),
        "missing_fields_for_training": [
            "incident_id",
            "wildfire_class (exclude structural / confirm ag-burning policy)",
            "latitude",
            "longitude",
            "onset_time_asia_manila (not only discovery/report time)",
            "ongoing_vs_new flag",
            "square_day reporting_coverage flag for negatives",
        ],
        "next_runnable_step": (
            "File a Mindanao onset CSV/GeoJSON under data/labels/philippines_onset/ with the "
            "missing fields above (BFP FOI microdata or DENR/LDRRMO extract), then re-run "
            "`python -m scripts.audit_philippines_onset_labels` and "
            "`python -m scripts.train_philippines_onset`."
        ),
        "harmonization_model_untouched": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit


def main() -> None:
    audit = build_audit()
    print(json.dumps({
        "path": str(OUT.relative_to(ROOT)),
        "usable_unique_wildfire_starts": audit["usable_unique_wildfire_starts"],
        "square_days_with_credible_reporting_coverage": audit["square_days_with_credible_reporting_coverage"],
        "publish_blocker": audit["publish_blocker"],
        "next_runnable_step": audit["next_runnable_step"],
    }, indent=2))


if __name__ == "__main__":
    main()
