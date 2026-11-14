"""Philippine 24-hour wildfire-onset forecast definitions.

Product question (when labels exist):
  “What is the estimated probability that at least one new wildfire will start
  in this 5 km square during the next 24 hours?”

Forecasts are issued at 00:00 Asia/Manila for the following Philippine day and
are stored separately from the live satellite layer, fire-weather outlook, and
MODIS–VIIRS harmonization model. This module never converts FWI, FIRMS counts,
or harmonization probabilities into an onset percentage.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from vela.settings import DATA_DIR, ROOT

MANILA = ZoneInfo("Asia/Manila")
SCOPE = "mindanao"
MODEL_FAMILY = "philippines_onset_24h"
AUDIT_PATH = DATA_DIR / "metrics" / "philippines_onset_label_audit.json"
SPLIT_PATH = DATA_DIR / "manifests" / "philippines_onset_split.json"
SELECTION_PATH = DATA_DIR / "models" / "philippines_onset_selection.json"
FEATURE_SCHEMA_VERSION = "onset_features_v1"

# Issue-time features the live app can know at Philippine midnight.
FEATURE_NAMES = [
    "heat_detections_in_cell_prior_24h",
    "heat_detections_neighbor_prior_24h",
    "hours_since_last_usable_pass",
    "usable_pass_count_prior_72h",
    "observation_coverage_prior_72h",
    "rainfall_mm_prior_24h_as_of_issue",
    "days_since_rain_as_of_issue",
    "forecast_temp_c_next_24h",
    "forecast_rh_percent_next_24h",
    "forecast_wind_kmh_next_24h",
    "month_sin",
    "month_cos",
]

TARGET_DEFINITION = {
    "question": (
        "Estimated probability that at least one new wildfire will start in this "
        "5 km square during the next 24 hours."
    ),
    "issue_time": "00:00 Asia/Manila",
    "valid_interval": "Philippine local day [issue_date, issue_date + 1 day)",
    "unit": "5 km EASE-Grid 2.0 land square",
    "positive": "Verified new wildfire onset inside the square during the valid interval",
    "negative": (
        "No verified onset AND reporting coverage is adequate for that square-day; "
        "otherwise outcome is unknown (not a negative)."
    ),
    "not_this_target": [
        "FIRMS / MODIS / VIIRS heat detections",
        "GWIS / FWI fire-danger class",
        "MODIS–VIIRS harmonization activity percentage",
        "Structural or vehicle fires without wildfire confirmation",
        "Agricultural burning unless independently labeled as wildfire onset",
        "Ongoing incidents that started before issue time",
    ],
}


def manila_now(now: datetime | None = None) -> datetime:
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(MANILA)


def philippine_issue_date(now: datetime | None = None) -> date:
    """Calendar date whose 00:00 Manila issue is the current Live forecast day."""

    local = manila_now(now)
    return local.date()


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


def load_audit(path: Path | None = None) -> dict[str, Any]:
    target = path or AUDIT_PATH
    if not target.is_file():
        return {
            "usable_unique_wildfire_starts": 0,
            "square_days_with_credible_reporting_coverage": 0,
            "status": "audit_missing",
            "path": str(target),
        }
    return json.loads(target.read_text(encoding="utf-8"))


def load_split(path: Path | None = None) -> dict[str, Any]:
    target = path or SPLIT_PATH
    if not target.is_file():
        return {"status": "split_missing", "path": str(target)}
    return json.loads(target.read_text(encoding="utf-8"))


def load_selection(path: Path | None = None) -> dict[str, Any] | None:
    target = path or SELECTION_PATH
    if not target.is_file():
        return None
    return json.loads(target.read_text(encoding="utf-8"))


def labels_sufficient(audit: dict[str, Any] | None = None) -> bool:
    payload = audit or load_audit()
    starts = int(payload.get("usable_unique_wildfire_starts") or 0)
    coverage = int(payload.get("square_days_with_credible_reporting_coverage") or 0)
    return starts > 0 and coverage > 0 and bool(payload.get("negatives_supported"))


def unavailable_reason(audit: dict[str, Any] | None = None) -> str:
    payload = audit or load_audit()
    if labels_sufficient(payload):
        selection = load_selection()
        if selection and selection.get("status") == "selected":
            return ""
        return (
            "Verified onset labels exist in the audit, but no frozen Philippine onset "
            "model has been selected yet. Run scripts/train_philippines_onset.py."
        )
    return (
        payload.get("publish_blocker")
        or "Insufficient verified Philippine wildfire-onset labels and reporting coverage."
    )


def forecast_for_cell(
    *,
    cell_id: str,
    issue_date: str | date | None = None,
    scope: str = SCOPE,
    store=None,
) -> dict[str, Any]:
    """Return the issued onset forecast for one square, or an explicit unavailable state."""

    from vela.onset_store import OnsetForecastStore

    day = str(issue_date or philippine_issue_date())[:10]
    audit = load_audit()
    reason = unavailable_reason(audit)
    interval = valid_interval(day)
    base = {
        "product": MODEL_FAMILY,
        "question": TARGET_DEFINITION["question"],
        "cell_id": cell_id,
        "scope": scope,
        "issue_date_ph": day,
        "issue_time_manila": issue_datetime_manila(day).isoformat(),
        "valid_interval": interval,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "harmonization_model_untouched": True,
        "label": "Estimated chance of a new wildfire in the next 24 hours",
    }
    if reason:
        return {
            **base,
            "status": "unavailable",
            "probability": None,
            "probability_percent": None,
            "model_version": None,
            "historical_simulation": False,
            "outcome": {"status": "unknown", "label": "Outcome unknown"},
            "reason": reason,
            "audit_path": str(AUDIT_PATH.relative_to(ROOT)) if str(AUDIT_PATH).startswith(str(ROOT)) else str(AUDIT_PATH),
            "next_step": payload_next_step(audit),
        }

    archive = store or OnsetForecastStore()
    issued = archive.get(cell_id=cell_id, issue_date_ph=day, scope=scope)
    if issued is None:
        return {
            **base,
            "status": "missing_issue",
            "probability": None,
            "probability_percent": None,
            "model_version": None,
            "historical_simulation": False,
            "outcome": archive.outcome_for(cell_id=cell_id, issue_date_ph=day) or {
                "status": "unknown",
                "label": "Outcome unknown",
            },
            "reason": (
                f"No onset forecast was issued for cell {cell_id} on {day} "
                f"(Philippine midnight). Live satellite updates do not rewrite a missing issue."
            ),
            "next_step": "Issue the daily Mindanao batch after a selected model exists.",
        }

    probability = issued.get("probability")
    percent = None if probability is None else int(round(float(probability) * 100))
    outcome = issued.get("outcome") or archive.outcome_for(cell_id=cell_id, issue_date_ph=day) or {
        "status": "unknown",
        "label": "Outcome unknown",
    }
    return {
        **base,
        **issued,
        "status": "issued",
        "probability": probability,
        "probability_percent": percent,
        "outcome": outcome,
        "reason": None,
    }


def payload_next_step(audit: dict[str, Any]) -> str:
    return (
        audit.get("next_runnable_step")
        or (
            "Obtain a Mindanao wildfire-onset table with geocoded starts, onset (not only "
            "discovery) timestamps, and square-day reporting coverage; place it under "
            "data/labels/philippines_onset/ and re-run scripts/audit_philippines_onset_labels.py."
        )
    )


def polygon_onset_summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Map square-level states without averaging into a polygon-wide wildfire chance."""

    issued = [row for row in cells if row.get("status") == "issued" and row.get("probability") is not None]
    highest = None
    if issued:
        highest = max(issued, key=lambda row: float(row["probability"]))
    return {
        "square_count": len(cells),
        "issued_count": len(issued),
        "unavailable_count": sum(1 for row in cells if row.get("status") == "unavailable"),
        "missing_count": sum(1 for row in cells if row.get("status") == "missing_issue"),
        "highest_estimated_square": None
        if highest is None
        else {
            "cell_id": highest.get("cell_id"),
            "probability_percent": highest.get("probability_percent"),
            "issue_date_ph": highest.get("issue_date_ph"),
            "model_version": highest.get("model_version"),
        },
        "polygon_probability": None,
        "polygon_probability_note": (
            "Vela does not present the average or maximum of square probabilities as the "
            "chance of a wildfire anywhere in the whole polygon."
        ),
    }
