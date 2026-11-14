"""Selected-location findings: satellite heat, frozen RF estimate, and weather.

Keeps weather outside the model's 14 VIIRS features. Never combines RF
probability, satellite count, and VPD into a wildfire score.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from vela.alert_passes import confirmation_evidence, pass_summary
from vela.contributions import (
    CALIBRATED_VIIRS,
    CALIBRATION_PENDING,
    OBSERVED_AQUA,
    UNAVAILABLE,
)
from vela.grid import cell_identifier, geographic_bounds, indices
from vela.meteomatics import FAO56_URL, MeteomaticsClient, empty_weather, weather_from_values
from vela.preparedness import forecast_point
from vela.serving import SELECTION_PATH, build_calendar, selected_method, week_cells
from vela.settings import DATA_DIR

RELIABILITY_PLAIN = (
    "Across four development weeks, the model’s estimated weekly share of active squares "
    "differed from Aqua’s observed share by 0.66 percentage points on average."
)
PHILIPPINE_STATUS = (
    "Philippine locations are supported for place labels and Asia/Manila times. "
    "They are not part of the training sample, and no Philippine held-out "
    "harmonization error has been measured."
)
HELD_OUT_STATUS = (
    "Pending verification. No held-out harmonization error has been measured. "
    "The 2023–2024 Reveal test and Pantanal transfer remain reserved."
)


def _monday(day: date) -> date:
    return date.fromordinal(day.toordinal() - day.weekday())


def _read_selection() -> dict:
    path = Path(SELECTION_PATH)
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def reliability_block(selection: dict | None = None) -> dict:
    """Development-selection reliability from the project validation artifact."""

    report = selection if selection is not None else _read_selection()
    mae = ((report.get("weekly_mae_percentage_points") or {}).get("random_forest"))
    chosen = report.get("chosen_model") or selected_method()
    scored = int(report.get("scored_weeks") or 0)
    matches_project = (
        chosen == "random_forest"
        and mae is not None
        and abs(float(mae) - 0.6598571873046138) < 1e-6
        and scored >= 4
        and report.get("selection_status") == "selected"
    )
    return {
        "metric": "Equal-weight weekly share mean absolute error",
        "metric_short": "weekly share MAE",
        "value_percentage_points": None if mae is None else round(float(mae), 2),
        "evaluation_period": "2021–2022 development / tune weeks",
        "validation_stage": "model selection on frozen candidates (not final Reveal test)",
        "scored_weeks": scored,
        "chosen_model": chosen,
        "final_test_evaluated": bool(report.get("final_test_evaluated")),
        "plain_language": RELIABILITY_PLAIN if matches_project else None,
        "held_out_status": HELD_OUT_STATUS,
        "philippine_status": PHILIPPINE_STATUS,
        "matches_project_record": matches_project,
        "note": (
            "This weekly error describes development selection performance. "
            "It is separate from a selected square’s model probability and is not a "
            "wildfire-confirmation percentage."
        ),
    }


def _scope_label(scope: str) -> str:
    if scope == "drawn_area":
        return "Your drawn area"
    return "Selected 5 km square"


def satellite_section(
    *,
    scope: str,
    observation_date: str,
    platforms: list[dict] | None = None,
    members: list[dict] | None = None,
    satellite_count: int | None = None,
    empty: bool = False,
    coverage_unknown: bool = False,
) -> dict:
    """Lead with distinct-pass wording when detection members are available."""

    rows = list(platforms or [])
    summary = pass_summary(
        members if members is not None else rows,
        observation_date=observation_date,
        empty=empty,
        coverage_unknown=coverage_unknown,
        scope=scope,
    )
    # Prefer pass-derived satellite rows when members produced passes.
    satellites = summary["satellites"] if summary["pass_count"] else rows
    count = (
        summary["pass_count"]
        if summary["pass_count"]
        else (satellite_count if satellite_count is not None else len({row.get("name") for row in rows if row.get("name")}))
    )
    return {
        "title": summary["title"],
        "lead": summary["lead"],
        "observation_date": observation_date,
        "scope": _scope_label(scope),
        "satellite_count": count,
        "pass_count": summary["pass_count"],
        "span_minutes": summary["span_minutes"],
        "passes": summary["passes"],
        "satellites": satellites,
        "empty": summary["empty"],
        "coverage_unknown": bool(coverage_unknown),
        "note": summary["note"],
    }


def _model_from_contribution(detail: dict | None, *, firms_only: bool = False) -> dict:
    reliability = reliability_block()
    base = {
        "title": "Model estimate",
        "reliability": reliability,
        "fao56_url": FAO56_URL,
        "features_note": (
            "Weather and air dryness are not inputs to the frozen random forest’s "
            "14 VIIRS features."
        ),
    }
    if firms_only or detail is None:
        return {
            **base,
            "status": "firms_only",
            "label": "Model estimate unavailable",
            "explanation": (
                "Only FIRMS hotspot points are available here, and the required "
                "VIIRS model features for this square and day are missing."
            ),
            "platform": None,
            "method": None,
            "observed_result": None,
            "model_probability": None,
            "raw_activity": None,
            "hotspot_pixel_count": None,
            "calibration_pending": False,
        }

    method = detail.get("method")
    platform = detail.get("platform")
    probability = detail.get("model_probability")
    raw = detail.get("raw_activity")
    detected = detail.get("detected")
    pending = bool(detail.get("calibration_pending"))

    if method == OBSERVED_AQUA:
        observed = "heat detected" if detected else "no heat detected"
        return {
            **base,
            "status": "observed_aqua",
            "label": "Observed by Aqua",
            "explanation": "Aqua supplied a valid observation for this square on that day.",
            "platform": platform,
            "method": method,
            "observed_result": observed,
            "model_probability": None,
            "raw_activity": None if detected is None else (1.0 if detected else 0.0),
            "hotspot_pixel_count": detail.get("hotspot_pixel_count"),
            "calibration_pending": False,
            "cell_id": detail.get("cell_id"),
            "local_date": detail.get("local_date"),
        }

    if method == CALIBRATED_VIIRS and probability is not None:
        return {
            **base,
            "status": "estimated_suomi",
            "label": "Estimated from Suomi-NPP",
            "explanation": (
                "The model estimates how likely Aqua would have been to detect heat "
                "in this square on that day."
            ),
            "platform": platform,
            "method": method,
            "observed_result": None,
            "model_probability": float(probability),
            "raw_activity": None if raw is None else float(raw),
            "hotspot_pixel_count": detail.get("hotspot_pixel_count"),
            "calibration_pending": False,
            "cell_id": detail.get("cell_id"),
            "local_date": detail.get("local_date"),
            "selected_method": detail.get("selected_method") or selected_method(),
        }

    if pending or platform in {"NOAA-20", "NOAA-21", "NOAA-20/NOAA-21"} or method == UNAVAILABLE:
        return {
            **base,
            "status": "noaa_raw",
            "label": "No calibrated estimate for this square",
            "explanation": (
                "Only NOAA-20/NOAA-21 FIRMS points are present here, so this square "
                "has no calibrated Aqua-comparable estimate."
            ),
            "platform": platform,
            "method": method or UNAVAILABLE,
            "observed_result": "heat detected" if detected else "no heat detected" if detected is False else None,
            "model_probability": None,
            "raw_activity": None if detected is None else (1.0 if detected else 0.0),
            "hotspot_pixel_count": detail.get("hotspot_pixel_count"),
            "calibration_pending": True,
            "calibration_status": CALIBRATION_PENDING,
            "cell_id": detail.get("cell_id"),
            "local_date": detail.get("local_date"),
        }

    return {
        **base,
        "status": "unavailable",
        "label": "Model estimate unavailable",
        "explanation": "No eligible Aqua observation or Suomi-NPP fallback estimate is available for this square and day.",
        "platform": platform,
        "method": method,
        "observed_result": None,
        "model_probability": None,
        "raw_activity": raw,
        "hotspot_pixel_count": detail.get("hotspot_pixel_count"),
        "calibration_pending": pending,
        "cell_id": detail.get("cell_id"),
        "local_date": detail.get("local_date"),
    }


def _noaa_only_platforms(platforms: list[dict] | None) -> bool:
    names = {
        str(row.get("name") or row.get("platform") or "").strip()
        for row in (platforms or [])
        if (row.get("name") or row.get("platform"))
    }
    names.discard("")
    return bool(names) and names.issubset({"NOAA-20", "NOAA-21"})


def model_for_cell_day(
    cell_id: str,
    observation_date: str,
    *,
    platforms: list[dict] | None = None,
) -> dict:
    """Reuse the backend’s chosen method for one cell-day via week_cells."""

    day = date.fromisoformat(str(observation_date)[:10])
    week_start = _monday(day).isoformat()
    x_text, y_text = str(cell_id).split(":", 1)
    west, south, east, north = geographic_bounds(int(x_text), int(y_text))
    pad = 0.01
    payload = week_cells(west - pad, south - pad, east + pad, north + pad, week_start)
    match = next(
        (
            item
            for item in payload.get("contributions") or []
            if item.get("cell_id") == cell_id and str(item.get("local_date") or "")[:10] == day.isoformat()
        ),
        None,
    )
    if match is None:
        if _noaa_only_platforms(platforms):
            return _model_from_contribution(
                {
                    "platform": "NOAA-20/NOAA-21",
                    "method": UNAVAILABLE,
                    "detected": True,
                    "calibration_pending": True,
                }
            )
        return _model_from_contribution(None, firms_only=True)
    return _model_from_contribution(match)


def model_for_drawn_area(west: float, south: float, east: float, north: float, observation_date: str) -> dict:
    """Area-week aggregate using Vela’s existing activity rate and denominator."""

    day = date.fromisoformat(str(observation_date)[:10])
    calendar = build_calendar(west, south, east, north, day.year)
    week = None
    for item in calendar.get("weeks") or []:
        start = date.fromisoformat(item["week_start"])
        end = date.fromisoformat(item["week_end"])
        if start <= day <= end:
            week = item
            break
    reliability = reliability_block()
    base = {
        "title": "Model estimate",
        "status": "area_aggregate",
        "label": "Weekly activity for your drawn area",
        "explanation": (
            "For a drawn area, Vela uses its existing weekly aggregate and denominator. "
            "Individual model probabilities appear only for a selected square and day."
        ),
        "reliability": reliability,
        "features_note": (
            "Weather and air dryness are not inputs to the frozen random forest’s "
            "14 VIIRS features."
        ),
        "cell_probabilities": "shown_only_for_selected_square",
    }
    if week is None:
        return {
            **base,
            "status": "unavailable",
            "label": "Model estimate unavailable",
            "explanation": "No published weekly estimate covers this drawn area on the selected date.",
            "activity_rate": None,
            "activity_denominator": None,
            "activity_status": None,
            "method_counts": None,
        }
    return {
        **base,
        "week_start": week.get("week_start"),
        "week_end": week.get("week_end"),
        "activity_rate": week.get("activity_rate"),
        "activity_denominator": week.get("activity_denominator"),
        "activity_status": week.get("activity_status"),
        "method_counts": week.get("method_counts"),
        "held_out": week.get("held_out"),
        "chosen_model": selected_method(),
    }


def point_for_scope(
    *,
    scope: str,
    lat: float | None,
    lon: float | None,
    west: float | None,
    south: float | None,
    east: float | None,
    north: float | None,
    cell_id: str | None,
) -> tuple[float, float]:
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    if cell_id and ":" in cell_id:
        x_text, y_text = cell_id.split(":", 1)
        cell_west, cell_south, cell_east, cell_north = geographic_bounds(int(x_text), int(y_text))
        return forecast_point(cell_west, cell_south, cell_east, cell_north)
    if None not in (west, south, east, north):
        return forecast_point(float(west), float(south), float(east), float(north))
    raise ValueError("A point or bounding box is required for weather.")


def build_findings(
    *,
    scope: str,
    observation_date: str,
    place_name: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    cell_id: str | None = None,
    platforms: list[dict] | None = None,
    members: list[dict] | None = None,
    satellite_count: int | None = None,
    empty: bool = False,
    coverage_unknown: bool = False,
    weather_valid_time: str | None = None,
    weather_client: MeteomaticsClient | None = None,
    weather_fixture: dict | None = None,
    region: str | None = None,
) -> dict:
    """Assemble selected-location findings: what happened, confirmation evidence, model, weather."""

    resolved_cell = cell_id
    if resolved_cell is None and lat is not None and lon is not None and scope != "drawn_area":
        x_index, y_index = indices(lon, lat)
        resolved_cell = cell_identifier(int(x_index), int(y_index))

    if scope == "drawn_area":
        if None in (west, south, east, north):
            raise ValueError("Drawn-area findings require a bounding box.")
        model = model_for_drawn_area(float(west), float(south), float(east), float(north), observation_date)
    else:
        if not resolved_cell:
            raise ValueError("Square findings require a cell_id or lat/lon.")
        model = model_for_cell_day(
            resolved_cell,
            observation_date,
            platforms=platforms,
        )

    satellite = satellite_section(
        scope=scope,
        observation_date=observation_date,
        platforms=platforms,
        members=members,
        satellite_count=satellite_count,
        empty=empty,
        coverage_unknown=coverage_unknown,
    )
    confirmation = confirmation_evidence(region=region or "Philippines")

    point_lat, point_lon = point_for_scope(
        scope=scope,
        lat=lat,
        lon=lon,
        west=west,
        south=south,
        east=east,
        north=north,
        cell_id=resolved_cell,
    )

    if weather_fixture is not None:
        weather = weather_from_values(
            latitude=point_lat,
            longitude=point_lon,
            valid_time=weather_fixture.get("valid_time")
            or weather_valid_time
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z"),
            temperature_c=weather_fixture.get("temperature_c"),
            relative_humidity_percent=weather_fixture.get("relative_humidity_percent"),
            wind_speed_kmh=weather_fixture.get("wind_speed_kmh"),
            wind_dir_deg=weather_fixture.get("wind_dir_deg"),
            precip_24h_mm=weather_fixture.get("precip_24h_mm"),
            optional_denied=weather_fixture.get("optional_denied") or [],
            fixture=True,
            kind=weather_fixture.get("kind") or "historical",
        )
    else:
        client = weather_client or MeteomaticsClient()
        try:
            weather = client.fetch_point(point_lat, point_lon, weather_valid_time)
        except Exception:  # noqa: BLE001
            weather = empty_weather("Weather request failed.")

    return {
        "place_name": place_name or "Selected location",
        "observation_date": observation_date,
        "scope": _scope_label(scope),
        "scope_code": scope,
        "cell_id": resolved_cell,
        "point": {"latitude": point_lat, "longitude": point_lon},
        "satellite": satellite,
        "confirmation": confirmation,
        "model": {
            **model,
            "panel": "research",
            "panel_note": (
                "The Aqua-comparable activity estimate stays in Research. "
                "It is not a wildfire probability."
            ),
        },
        "weather": weather,
        "research": {
            "held_out_status": HELD_OUT_STATUS,
            "philippine_status": PHILIPPINE_STATUS,
            "fao56_url": FAO56_URL,
            "model": model,
            "confirmation": confirmation,
            "reserve_week_note": (
                "Reserve-week context and regional breakdown stay in Research. "
                "Weekly selection error stays separate from a square’s probability."
            ),
        },
    }


# Zambia woodland worked example used in verification.
ZAMBIA_CELL_ID = "523:-383"
ZAMBIA_DATE = "2021-07-22"
ZAMBIA_BOX = (25.0, -15.5, 29.0, -12.5)
