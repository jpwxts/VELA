"""Issue-time features for Philippine onset forecasts.

A satellite pass or weather product published after Philippine midnight cannot
be used to recreate what Vela knew at issue time. Each feature carries
observation_time and availability_time when known; missing inputs are flagged.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from vela.grid import cell_identifier, center, geographic_bounds, indices
from vela.onset_forecast import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, issue_datetime_manila

MANILA = ZoneInfo("Asia/Manila")


def _parse_acq_utc(spot: dict) -> datetime | None:
    acq_date = str(spot.get("acq_date") or "")[:10]
    acq_time = str(spot.get("acq_time") or "00:00")
    if not acq_date:
        return None
    if ":" not in acq_time and acq_time.isdigit():
        acq_time = f"{acq_time.zfill(4)[:2]}:{acq_time.zfill(4)[2:]}"
    try:
        return datetime.fromisoformat(f"{acq_date}T{acq_time}:00").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(f"{acq_date}T{acq_time}").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def neighbor_cell_ids(cell_id: str) -> list[str]:
    x_text, y_text = str(cell_id).split(":", 1)
    x_index, y_index = int(x_text), int(y_text)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            out.append(cell_identifier(x_index + dx, y_index + dy))
    return out


def build_issue_time_features(
    *,
    cell_id: str,
    issue_date_ph: str | date,
    detections: list[dict] | None = None,
    weather_forecast: dict | None = None,
    rainfall_history: dict | None = None,
) -> dict[str, Any]:
    """Build the feature vector known at 00:00 Asia/Manila on issue_date_ph."""

    issue_local = issue_datetime_manila(issue_date_ph)
    issue_utc = issue_local.astimezone(timezone.utc)
    prior_24h_start = issue_utc - timedelta(hours=24)
    prior_72h_start = issue_utc - timedelta(hours=72)

    lon, lat = center(*map(int, str(cell_id).split(":")))
    neighbors = set(neighbor_cell_ids(cell_id))
    in_cell = []
    in_neighbors = []
    usable_passes = []
    for spot in detections or []:
        observed = _parse_acq_utc(spot)
        available_raw = spot.get("retrieved_at") or spot.get("availability_time")
        available = None
        if available_raw:
            try:
                available = datetime.fromisoformat(str(available_raw).replace("Z", "+00:00"))
                if available.tzinfo is None:
                    available = available.replace(tzinfo=timezone.utc)
            except ValueError:
                available = None
        # Availability gate: if unknown, treat observation time as availability
        # only when the acquisition itself is before issue (conservative for audit demos).
        gate = available or observed
        if observed is None or gate is None or gate > issue_utc or observed > issue_utc:
            continue
        x_index, y_index = indices(float(spot["lon"]), float(spot["lat"]))
        spot_cell = cell_identifier(int(x_index), int(y_index))
        if spot_cell == cell_id and observed >= prior_24h_start:
            in_cell.append(spot)
        if spot_cell in neighbors and observed >= prior_24h_start:
            in_neighbors.append(spot)
        if observed >= prior_72h_start:
            usable_passes.append(observed)

    hours_since = None
    if usable_passes:
        latest = max(usable_passes)
        hours_since = (issue_utc - latest).total_seconds() / 3600.0

    month = issue_local.month
    weather = weather_forecast or {}
    rain = rainfall_history or {}
    weather_available = weather.get("availability_time")
    weather_ok = False
    if weather_available:
        try:
            stamp = datetime.fromisoformat(str(weather_available).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            weather_ok = stamp <= issue_utc
        except ValueError:
            weather_ok = False
    elif weather:
        # Explicit archive marked as issued-at or before issue.
        weather_ok = bool(weather.get("issued_at_or_before_issue"))

    values = {
        "heat_detections_in_cell_prior_24h": float(len(in_cell)),
        "heat_detections_neighbor_prior_24h": float(len(in_neighbors)),
        "hours_since_last_usable_pass": hours_since,
        "usable_pass_count_prior_72h": float(len(usable_passes)),
        "observation_coverage_prior_72h": 1.0 if usable_passes else 0.0,
        "rainfall_mm_prior_24h_as_of_issue": rain.get("rainfall_mm_prior_24h") if rain.get("as_of_issue") else None,
        "days_since_rain_as_of_issue": rain.get("days_since_rain") if rain.get("as_of_issue") else None,
        "forecast_temp_c_next_24h": weather.get("temperature_c") if weather_ok else None,
        "forecast_rh_percent_next_24h": weather.get("relative_humidity_percent") if weather_ok else None,
        "forecast_wind_kmh_next_24h": weather.get("wind_speed_km_h") if weather_ok else None,
        "month_sin": math.sin(2 * math.pi * month / 12.0),
        "month_cos": math.cos(2 * math.pi * month / 12.0),
    }
    missing = [name for name in FEATURE_NAMES if values.get(name) is None]
    reduced_baseline = len(missing) > 0
    return {
        "cell_id": cell_id,
        "issue_date_ph": str(issue_date_ph)[:10],
        "issue_time_manila": issue_local.isoformat(),
        "issue_time_utc": issue_utc.isoformat(),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "center": {"lon": lon, "lat": lat},
        "bounds": dict(
            zip(("west", "south", "east", "north"), geographic_bounds(*map(int, str(cell_id).split(":"))))
        ),
        "values": {name: values.get(name) for name in FEATURE_NAMES},
        "missing_features": missing,
        "reduced_feature_baseline": reduced_baseline,
        "input_timestamps": {
            "detections_used": len(in_cell) + len(in_neighbors),
            "latest_usable_pass_utc": None if not usable_passes else max(usable_passes).isoformat(),
            "weather_availability_time": weather.get("availability_time"),
            "rainfall_as_of_issue": bool(rain.get("as_of_issue")),
        },
        "notes": [
            "Features use only inputs available at or before Philippine midnight.",
            "Missing weather or rainfall fields trigger the reduced-feature baseline path.",
        ],
    }
