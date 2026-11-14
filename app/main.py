"""Local web app for Vela. The map key is read here and never sent to the browser."""

from __future__ import annotations

import csv
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.db import ResponseCache
from app.firms import FirmsClient
from app.geocode import SOURCE as PLACE_SOURCE, identify_selection, search_places
from app.mailer import send_test_brief
from vela.calendar_metrics import CALENDAR_METRIC
from vela.coverage import COVERAGE_RULE
from vela.forecast_store import ForecastArchive
from vela.history import build_monthly_history
from vela.preparedness import (
    build_day_outlook,
    build_forecast,
    draft_brief,
    explain_day,
    issue_forecast,
    load_model_report,
    region_key,
    request_bytes,
    verification_status,
)
from vela.serving import (
    TRACE_PATH,
    TRACES_PATH,
    build_calendar,
    calendar_rows,
    list_calendar_years,
    model_status,
    read_job,
    region_label,
    reveal_week,
    week_cells,
)
from vela.settings import DATA_DIR, ROOT, regions, settings

load_dotenv(ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def http_get(url: str) -> tuple[int, str]:
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        return response.status_code, response.text


def build_firms() -> FirmsClient:
    cfg = settings()
    return FirmsClient(
        os.environ.get("FIRMS_MAP_KEY", ""),
        ResponseCache(DATA_DIR / "cache" / "firms.sqlite"),
        http_get,
        max_span=float(cfg["max_request_span_degrees"]),
        day_range=1,
    )


FIRMS = build_firms()
ARCHIVE = ForecastArchive(DATA_DIR / "preparedness" / "forecasts.sqlite")
OBSERVATION_PLATFORMS = ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    print("\nVela is running. Open http://127.0.0.1:8000\n", flush=True)
    yield


app = FastAPI(title="Vela", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AreaRequest(BaseModel):
    west: float
    south: float
    east: float
    north: float
    date: str
    platforms: list[str] = Field(default_factory=lambda: ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"])


class ObservationAskRequest(BaseModel):
    west: float
    south: float
    east: float
    north: float
    date: str
    lat: float
    lon: float
    platforms: list[str] = Field(default_factory=lambda: ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"])


class BriefRequest(BaseModel):
    west: float
    south: float
    east: float
    north: float
    issue_id: str
    valid_date: str
    confirm: bool = False


class RevealRequest(BaseModel):
    west: float
    south: float
    east: float
    north: float
    week_start: str


class CheckLandRequest(BaseModel):
    """Visitor land boundary as a closed or open lon/lat ring."""

    coordinates: list[list[float]] = Field(..., min_length=3)
    date: str | None = None
    platforms: list[str] = Field(default_factory=lambda: ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"])
    label: str | None = None
    include_hotspots: bool = True


class HistoryRequest(BaseModel):
    coordinates: list[tuple[float, float]] = Field(..., min_length=3, max_length=2000)
    year: int = Field(..., ge=1990, le=9998)
    month: int = Field(..., ge=1, le=12)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    return {
        "metric": CALENDAR_METRIC,
        "coverage_rule": COVERAGE_RULE,
        "firms_configured": bool(os.environ.get("FIRMS_MAP_KEY", "").strip()),
        "model": model_status(),
        "progress": read_job(),
        "supported_platform": settings()["supported_platform"],
    }


@app.get("/api/regions")
def example_regions():
    return [
        {
            "id": region["id"],
            "name": region["name"],
            "landscape": region["landscape"],
            "role": region["role"],
            "west": region["west"],
            "south": region["south"],
            "east": region["east"],
            "north": region["north"],
        }
        for region in regions()
    ]


@app.get("/api/geocode")
def geocode(q: str = Query(min_length=2)):
    try:
        return {"places": search_places(q), "source": PLACE_SOURCE}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Place search failed. Draw a rectangle instead.") from exc


class PlaceRequest(BaseModel):
    """On-demand place identification for a tap, detection, or 5 km square."""

    mode: str = Field(default="point", pattern="^(point|center|members)$")
    lat: float | None = None
    lon: float | None = None
    center_lat: float | None = None
    center_lon: float | None = None
    members: list[dict] = Field(default_factory=list)


PLACE_CACHE = ResponseCache(DATA_DIR / "cache" / "places.sqlite")


@app.get("/api/place")
def place_get(
    lat: float = Query(...),
    lon: float = Query(...),
    mode: str = Query(default="point", pattern="^(point|center)$"),
):
    """Reverse-geocode one selected point. Cached; not called for every marker on load."""

    return identify_selection(mode=mode, lat=lat, lon=lon, cache=PLACE_CACHE)


@app.post("/api/place")
def place_post(body: PlaceRequest):
    """Reverse-geocode a point or the readings inside a selected 5 km square."""

    if body.mode == "members" and not body.members and body.lat is None:
        raise HTTPException(status_code=400, detail="Members or a center point are required.")
    if body.mode != "members" and (body.lat is None or body.lon is None):
        raise HTTPException(status_code=400, detail="Latitude and longitude are required.")
    return identify_selection(
        mode=body.mode,
        lat=body.lat,
        lon=body.lon,
        members=body.members,
        center_lat=body.center_lat,
        center_lon=body.center_lon,
        cache=PLACE_CACHE,
    )


@app.post("/api/hotspots")
def hotspots(body: AreaRequest):
    return FIRMS.hotspots(body.west, body.south, body.east, body.north, body.date, body.platforms)


@app.get("/api/hotspots/fixture")
def hotspots_fixture(name: str = "click_regression"):
    """Labeled regression payloads for public UI click tests. Not live FIRMS data."""

    import json

    fixtures = {
        "click_regression": DATA_DIR / "fixtures" / "hotspot_click_regression_7areas_8dets.json",
        "two_satellites": DATA_DIR / "fixtures" / "hotspot_two_satellites.json",
    }
    path = fixtures.get(name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown hotspot fixture.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "fixture" not in payload or not isinstance(payload.get("fixture"), dict):
        payload["fixture"] = {"name": name}
    defaults = {
        "click_regression": "Regression fixture · 7 areas · 8 NOAA-20 detections · not a live FIRMS pull",
        "two_satellites": "Two-satellite click fixture · NOAA-20 + NOAA-21 in one 5 km cell · labeled archive",
    }
    payload["fixture"].setdefault("label", defaults.get(name, f"Hotspot fixture · {name}"))
    payload["fixture"]["name"] = name
    return payload


@app.get("/api/public/philippines/{day}.geojson")
def public_philippines_geojson(day: str):
    """Raw shareable GeoJSON for one Philippine FIRMS snapshot day."""

    from vela.public_hotspots import geojson_path

    path = geojson_path(day)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Public hotspot GeoJSON not found.")
    return FileResponse(
        path,
        media_type="application/geo+json",
        filename=f"{day}.geojson",
    )


@app.get("/api/public/philippines/{day}")
def public_philippines_hotspots(day: str, region: str = Query("philippines")):
    """Saved Philippine FIRMS snapshot as a land-check payload (no NASA key)."""

    from vela.public_hotspots import build_public_land_check

    try:
        return build_public_land_check(day=day, region=region)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/area-context")
def area_context(
    west: float,
    south: float,
    east: float,
    north: float,
    date: str,
    cell_id: str | None = None,
):
    """Calendar baseline + upcoming fire weather for a selected 5 km square."""

    from datetime import date as date_cls
    from vela.land_check import annotate_forecast_days

    try:
        year = int(str(date)[:4])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Observation date is required.") from exc

    calendar = build_calendar(west, south, east, north, year)
    region = calendar.get("region") or {}
    region_id = region.get("region_id")
    region_name = None
    if region_id:
        match = next((item for item in regions() if item.get("id") == region_id), None)
        region_name = None if match is None else match.get("name")
    if not region_name and region.get("code") == "represented_in_training":
        region_name = "the overlapping training region"
    weeks = calendar.get("weeks") or []
    observation = date_cls.fromisoformat(str(date))
    matching = []
    for week in weeks:
        start = date_cls.fromisoformat(week["week_start"])
        end = date_cls.fromisoformat(week["week_end"])
        if start <= observation <= end:
            matching.append(week)
    comparable = [
        week
        for week in weeks
        if week.get("coverage_status") == "ok"
        and week.get("activity_status") not in {None, "unavailable", "hidden"}
        and week.get("activity_rate") is not None
    ]
    baseline_years = sorted({int(week["week_start"][:4]) for week in comparable})
    if calendar.get("status") != "ok" or not comparable:
        unusual = {
            "status": "insufficient",
            "text": "Not enough comparable fire-calendar history with adequate coverage is available for this square.",
            "region_name": region_name,
            "baseline_years": [],
            "week": matching[0] if matching else None,
        }
    else:
        rates = [float(week["activity_rate"]) for week in comparable]
        median = sorted(rates)[len(rates) // 2]
        this_week = matching[0] if matching else None
        this_rate = None if not this_week else this_week.get("activity_rate")
        scope = (
            f"the {region_name} region"
            if region_name
            else "the selected search area"
        )
        if this_rate is None:
            text = (
                f"Comparable weeks are available for {scope}, but this observation week "
                "does not yet have a usable activity rate."
            )
            status = "incomplete_week"
        elif float(this_rate) > median:
            text = (
                f"For {scope}, this week’s harmonized activity rate "
                f"({float(this_rate) * 100:.1f}% of usable cell-days) is above the median "
                f"of comparable weeks in {', '.join(str(y) for y in baseline_years)} "
                f"({median * 100:.1f}%). Satellite count alone does not establish unusual activity."
            )
            status = "above_median"
        else:
            text = (
                f"For {scope}, this week’s harmonized activity rate "
                f"({float(this_rate) * 100:.1f}% of usable cell-days) is at or below the median "
                f"of comparable weeks in {', '.join(str(y) for y in baseline_years)} "
                f"({median * 100:.1f}%). Satellite count alone does not establish unusual activity."
            )
            status = "at_or_below_median"
        unusual = {
            "status": status,
            "text": text,
            "region_name": region_name,
            "baseline_years": baseline_years,
            "week": this_week,
            "median_activity_rate": median,
        }

    forecast = build_forecast(west, south, east, north, request_bytes, load_model_report())
    if forecast.get("ok"):
        forecast = issue_forecast(ARCHIVE, forecast)
    outlook = annotate_forecast_days(forecast)
    return {
        "cell_id": cell_id,
        "observation_date": date,
        "unusual": unusual,
        "forecast": outlook,
        "calendar_status": calendar.get("status"),
    }


@app.post("/api/check-land")
def check_land(body: CheckLandRequest):
    """Forecast fire danger for a plot plus satellite heat inside or nearby the boundary."""

    from datetime import date as date_cls, timedelta
    from vela.land_check import build_land_check, normalize_ring, polygon_bbox

    try:
        ring = normalize_ring(body.coordinates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    west, south, east, north = polygon_bbox(ring)
    # Expand the FIRMS query slightly so "nearby" detections just outside the fence are returned.
    pad = 0.05
    query_box = (west - pad, south - pad, east + pad, north + pad)
    forecast = build_forecast(west, south, east, north, request_bytes, load_model_report())
    if forecast.get("ok"):
        forecast = issue_forecast(ARCHIVE, forecast)

    observation_date = body.date
    if not observation_date:
        observation_date = (date_cls.today() - timedelta(days=1)).isoformat()

    if body.include_hotspots:
        hotspots_payload = FIRMS.hotspots(
            *query_box, observation_date, body.platforms or OBSERVATION_PLATFORMS
        )
    else:
        hotspots_payload = {
            "configured": bool(FIRMS.key),
            "date": observation_date,
            "bbox": {"west": west, "south": south, "east": east, "north": north},
            "total_count": 0,
            "combined": {"coverage": "unknown"},
            "results": [],
        }

    return build_land_check(
        ring=ring,
        forecast=forecast,
        hotspot_payload=hotspots_payload,
        label=body.label,
        observation_date=observation_date,
    )


@app.get("/api/check-land/fixture")
def check_land_fixture(name: str = "check_land_demo"):
    """Labeled competition demo. Forecast and detections are saved, not live."""

    import json
    from copy import deepcopy

    from vela.land_check import build_land_check

    fixtures = {
        "check_land_demo": DATA_DIR / "fixtures" / "check_land_demo.json",
    }
    path = fixtures.get(name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown land-check fixture.")
    saved = json.loads(path.read_text(encoding="utf-8"))
    payload = build_land_check(
        ring=saved["polygon"]["coordinates"][0],
        forecast=deepcopy(saved["forecast"]),
        hotspot_payload=deepcopy(saved["hotspots"]),
        label=saved.get("label"),
        observation_date=saved.get("observation_date"),
        fixture=saved.get("fixture")
        or {
            "name": name,
            "label": "Saved competition demo · labeled archive, not a live network pull",
        },
    )
    payload["saved"] = True
    return payload


@app.get("/api/preparedness/fixture")
def preparedness_fixture(name: str = "weather_outlook_amazon"):
    """Labeled Weather outlook fixture for the blank-card regression."""

    import json
    from copy import deepcopy

    from vela.land_check import annotate_forecast_days

    fixtures = {
        "weather_outlook_amazon": DATA_DIR / "fixtures" / "weather_outlook_amazon.json",
        "weather_values_missing": DATA_DIR / "fixtures" / "weather_values_missing.json",
        "weather_no_fwi": DATA_DIR / "fixtures" / "weather_no_fwi.json",
    }
    path = fixtures.get(name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Unknown weather fixture.")
    saved = json.loads(path.read_text(encoding="utf-8"))
    forecast = annotate_forecast_days(deepcopy(saved["forecast"]))
    forecast["fixture"] = saved.get("fixture") or {"name": name, "label": "Saved weather fixture"}
    forecast["bbox"] = saved.get("bbox")
    forecast["saved"] = True
    forecast["performance"] = saved.get("forecast", {}).get("performance") or {
        "status": "pending_verification",
        "text": "Pending verification. No held-out harmonization error has been measured.",
    }
    return forecast


@app.get("/api/wildfire-report")
def wildfire_report(
    west: float,
    south: float,
    east: float,
    north: float,
    date: str,
    cell_id: str | None = None,
):
    from vela.wildfire_reports import lookup_wildfire_report

    return lookup_wildfire_report(
        west=west, south=south, east=east, north=north, date=date, cell_id=cell_id
    )


@app.post("/api/observation-ask")
def observation_ask(body: ObservationAskRequest):
    """Ask whether a tapped square was observed, without inventing a clear zero."""

    from vela.grid import cell_identifier, indices
    from vela.hotspot_areas import platform_status_for_cell

    payload = FIRMS.hotspots(body.west, body.south, body.east, body.north, body.date, body.platforms)
    x_index, y_index = indices(body.lon, body.lat)
    cell_id = cell_identifier(int(x_index), int(y_index))
    statuses = platform_status_for_cell(payload, cell_id, body.date)
    detected = [row for row in statuses if row.get("state") == "detected"]
    if detected:
        text = "Satellites detected heat in this square."
        kind = "detected"
    elif any(row.get("state") == "observed_no_heat" for row in statuses):
        text = "Satellites observed this square. No heat was detected during the measured pass."
        kind = "observed_no_heat"
    else:
        text = "We don’t know whether satellites had a clear view here."
        kind = "unknown"
    return {
        "cell_id": cell_id,
        "lat": body.lat,
        "lon": body.lon,
        "date": body.date,
        "kind": kind,
        "text": text,
        "platform_statuses": statuses,
        "hotspot_areas": payload.get("hotspot_areas"),
        "never_treat_missing_as_zero": True,
    }


@app.get("/api/calendar")
def calendar(west: float, south: float, east: float, north: float, year: int):
    return build_calendar(west, south, east, north, year)


@app.post("/api/history/month")
def monthly_history(body: HistoryRequest):
    """Daily calendar and monthly chart totals for the visitor's actual boundary."""

    import math
    from datetime import date
    from vela.land_check import normalize_ring, polygon_bbox

    if body.year > date.today().year:
        raise HTTPException(status_code=400, detail="Choose a year up to the current year.")
    if any(not math.isfinite(lon) or not math.isfinite(lat) or abs(lon) > 180 or abs(lat) > 90
           for lon, lat in body.coordinates):
        raise HTTPException(status_code=400, detail="Use valid longitude and latitude coordinates.")
    ring = normalize_ring(body.coordinates)
    west, south, east, north = polygon_bbox(ring)
    area = abs(sum(left[0] * right[1] - right[0] * left[1] for left, right in zip(ring, ring[1:])))
    if west == east or south == north or len(set(map(tuple, ring))) < 3 or area < 1e-12:
        raise HTTPException(status_code=400, detail="Select a boundary with an area.")
    return build_monthly_history(ring, body.year, body.month)


@app.get("/api/calendar/years")
def calendar_years(west: float, south: float, east: float, north: float):
    """Years with published weekly estimates for the selected land."""

    return list_calendar_years(west, south, east, north)


@app.get("/api/calendar/cells")
def calendar_cells(west: float, south: float, east: float, north: float, week_start: str):
    return week_cells(west, south, east, north, week_start)


@app.post("/api/reveal")
def reveal(body: RevealRequest):
    return reveal_week(body.west, body.south, body.east, body.north, body.week_start)


@app.get("/api/export.csv")
def export_csv(
    west: float,
    south: float,
    east: float,
    north: float,
    year: int,
    include_observed: bool = False,
):
    payload = build_calendar(west, south, east, north, year)
    rows = calendar_rows(payload, include_observed=include_observed)
    buffer = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else ["week_start"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="vela-{year}.csv"'},
    )


@app.get("/api/trace")
def trace():
    import json

    path = TRACES_PATH if TRACES_PATH.is_file() else TRACE_PATH
    if not path.is_file():
        return {"available": False, "examples": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    examples = payload.get("examples")
    if not examples:
        examples = [payload]
    return {
        "available": True,
        "source_pass": payload.get("source_pass"),
        "examples": examples,
    }


@app.get("/api/models")
def models():
    return _artifact_summary()


@app.get("/api/preparedness")
def preparedness(west: float, south: float, east: float, north: float):
    from vela.land_check import annotate_forecast_days

    forecast = build_forecast(west, south, east, north, request_bytes, load_model_report())
    if forecast.get("ok"):
        forecast = issue_forecast(ARCHIVE, forecast)
    forecast["performance"] = forecast.get("performance") or {}
    # Public outlook fields (headline, GWIS classes, readable archive time).
    annotated = annotate_forecast_days(forecast)
    annotated["performance"] = forecast.get("performance") or {}
    return annotated


@app.get("/api/day-outlook")
def day_outlook(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
):
    """Temperature and wind through today near one point (the land's center)."""

    return build_day_outlook(lat, lon, request_bytes)


@app.get("/api/preparedness/day")
def preparedness_day(
    issue_id: str,
    valid_date: str,
    west: float,
    south: float,
    east: float,
    north: float,
):
    stored = _stored_forecast(issue_id, west, south, east, north)
    day = next((item for item in stored.get("days") or [] if item.get("valid_date") == valid_date), None)
    if day is None:
        raise HTTPException(status_code=404, detail="That forecast day is not in the issued forecast.")
    hotspots = _latest_hotspots(west, south, east, north)
    return {
        "day": day,
        "explanation": explain_day(day),
        "hotspots": hotspots,
        "brief": draft_brief(stored, day, hotspots),
        "already_sent": ARCHIVE.brief_already_sent(stored["region_key"], issue_id),
        "performance": stored.get("performance"),
        "issued_at": stored.get("issued_at"),
    }


@app.post("/api/preparedness/brief")
def preparedness_brief(body: BriefRequest):
    stored = _stored_forecast(body.issue_id, body.west, body.south, body.east, body.north)
    day = next((item for item in stored.get("days") or [] if item.get("valid_date") == body.valid_date), None)
    if day is None:
        raise HTTPException(status_code=404, detail="That forecast day is not in the issued forecast.")
    hotspots = _latest_hotspots(body.west, body.south, body.east, body.north)
    brief = draft_brief(stored, day, hotspots)
    if not body.confirm:
        return {"sent": False, "status": "review", "brief": brief}
    if ARCHIVE.brief_already_sent(stored["region_key"], body.issue_id):
        return {
            "sent": False,
            "status": "duplicate",
            "brief": brief,
            "message": "A brief for this region and forecast issue was already sent.",
        }
    result = send_test_brief(f"Vela preparedness brief {day['valid_date']}", brief)
    if result.get("sent"):
        ARCHIVE.mark_brief_sent(stored["region_key"], body.issue_id)
    result["brief"] = brief
    return result


def _stored_forecast(issue_id: str, west: float, south: float, east: float, north: float) -> dict:
    stored = ARCHIVE.get(issue_id)
    if stored is None or stored.get("region_key") != region_key(west, south, east, north):
        raise HTTPException(status_code=404, detail="No issued forecast matches this area.")
    return stored


def _latest_hotspots(west: float, south: float, east: float, north: float) -> dict:
    if not FIRMS.key:
        return {
            "observation_status": "missing",
            "date": None,
            "total_count": 0,
            "results": [],
            "message": "FIRMS_MAP_KEY is not set. Add it to the .env file in this project, then restart Vela. The key is not shown here.",
        }
    day = FIRMS.latest_available_day(OBSERVATION_PLATFORMS)
    if not day:
        return {
            "observation_status": "missing",
            "date": None,
            "total_count": 0,
            "results": [],
            "message": "The latest NASA observation date is unavailable.",
        }
    payload = FIRMS.hotspots(west, south, east, north, day, OBSERVATION_PLATFORMS)
    results = payload.get("results") or []
    failed = [item for item in results if item.get("status") in {"request_failed", "not_configured", "area_too_large"}]
    if payload.get("total_count", 0) > 0:
        status = "measured"
        message = ""
    elif failed and not any(item.get("status") == "no_hotspots" for item in results):
        status = "missing"
        message = failed[0].get("message") or "The NASA hotspot request failed."
    elif results and all(item.get("status") == "no_hotspots" for item in results):
        status = "no_hotspots"
        message = "No hotspots returned."
    else:
        status = "missing"
        message = "Hotspot observations are missing."
    return {
        "observation_status": status,
        "date": payload.get("date") or day,
        "total_count": payload.get("total_count") or 0,
        "results": results,
        "message": message,
    }


def _artifact_summary() -> dict:
    from vela.serving import selected_method

    models = DATA_DIR / "models"
    pilot = _read_model_json(models / "pilot_report.json")
    candidates = _read_model_json(models / "candidate_report.json")
    selection = _read_model_json(models / "report.json")
    reserve = _read_model_json(models / "reserve_inclusive_selection.json") or {}
    counts = (candidates or {}).get("counts") or {}
    checks = (pilot or {}).get("checks") or {}
    chosen = selected_method()
    return {
        "pilot": {
            "exists": (models / "pilot_logistic_log1p.joblib").is_file(),
            "training_rows": checks.get("eligible_cells"),
            "dates": checks.get("eligible_dates"),
            "purpose": (pilot or {}).get("purpose"),
        },
        "logistic_regression": {
            "exists": (models / "candidate_logistic_regression.joblib").is_file(),
            "training_rows": counts.get("train_rows"),
            "regions": counts.get("train_regions"),
            "years": counts.get("train_years"),
        },
        "random_forest": {
            "exists": (models / "candidate_random_forest.joblib").is_file(),
            "training_rows": counts.get("train_rows"),
            "regions": counts.get("train_regions"),
            "years": counts.get("train_years"),
        },
        "final_model": {
            "exists": (models / "vela_model.joblib").is_file(),
            "chosen_model": chosen,
            "selection_status": reserve.get("selection_status") or (selection or {}).get("selection_status"),
            "final_test_evaluated": bool(reserve.get("final_test_evaluated") or (selection or {}).get("final_test_evaluated")),
        },
        "independent_validation_report": verification_status(selection).get("status") == "measured",
        "performance": verification_status(selection),
    }


def _read_model_json(path):
    if not path.is_file():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/region-label")
def label(west: float, south: float, east: float, north: float):
    return region_label(west, south, east, north)
