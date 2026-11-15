"""Surface weather at each satellite hotspot, at the hour the satellite passed.

A land check reads its seven-day outlook at one point near the centre of the
boundary. Hotspots are separate pixels with their own locations and pass times,
so each one gets its own reading: the weather-model grid point nearest that
pixel, at the UTC hour nearest the satellite pass.

Points on the same UTC day are batched into one multi-location Open-Meteo
request. Recent days come from the forecast API (which keeps about three months
of past hours); older days come from the ERA5 archive. A failed request marks
only its own points unavailable; nothing is filled in from another point.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from vela.preparedness import wind_direction_text

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "wind_direction_10m",
    "precipitation",
)
# The forecast API serves roughly 92 past days; stay inside that with a margin.
FORECAST_PAST_DAYS = 85
BATCH_SIZE = 50
MAX_POINTS = 200
WORKERS = 6
SOURCE = "Open-Meteo (forecast API for recent days, ERA5 archive for older days)"

Getter = Callable[[str, dict], tuple[int, bytes]]


def _clock(value) -> tuple[int, int] | None:
    text = str(value or "").strip()
    if not text:
        return None
    if ":" in text:
        hours, _, minutes = text.partition(":")
    else:
        digits = text.zfill(4)
        if not digits.isdigit() or len(digits) != 4:
            return None
        hours, minutes = digits[:2], digits[2:]
    try:
        hour, minute = int(hours), int(minutes[:2])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def pass_hour_utc(acq_date, acq_time) -> datetime | None:
    """The UTC hour nearest a FIRMS acquisition (acq_date + acq_time are UTC)."""

    try:
        day = date.fromisoformat(str(acq_date or "")[:10])
    except ValueError:
        return None
    clock = _clock(acq_time)
    if clock is None:
        return None
    stamp = datetime(day.year, day.month, day.day, clock[0], clock[1], tzinfo=timezone.utc)
    if stamp.minute >= 30:
        stamp += timedelta(hours=1)
    return stamp.replace(minute=0)


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def _empty(point_id, lat, lon, status: str, valid_time: str | None = None) -> dict:
    return {
        "id": point_id,
        "lat": lat,
        "lon": lon,
        "status": status,
        "valid_time_utc": valid_time,
        "air_temperature_c": None,
        "relative_humidity_percent": None,
        "wind_speed_km_h": None,
        "wind_direction_deg": None,
        "wind_direction_text": None,
        "precipitation_mm": None,
        "grid_latitude": None,
        "grid_longitude": None,
        "elevation_m": None,
    }


def _request(url: str, coords: list[tuple[float, float]], day: date) -> tuple[str, dict]:
    return url, {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in coords),
        "longitude": ",".join(f"{lon:.4f}" for _, lon in coords),
        "hourly": ",".join(HOURLY_FIELDS),
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
        "timezone": "GMT",
        "wind_speed_unit": "kmh",
    }


def _read_location(location: dict, hour_key: str) -> dict | None:
    hourly = location.get("hourly") or {}
    times = [str(stamp)[:13] for stamp in hourly.get("time") or []]
    try:
        index = times.index(hour_key)
    except ValueError:
        return None

    def at(name: str):
        values = hourly.get(name) or []
        return _number(values[index]) if index < len(values) else None

    temperature = at("temperature_2m")
    humidity = at("relative_humidity_2m")
    wind = at("wind_speed_10m")
    direction = at("wind_direction_10m")
    rain = at("precipitation")
    return {
        "air_temperature_c": None if temperature is None else round(temperature, 1),
        "relative_humidity_percent": None if humidity is None else round(humidity),
        "wind_speed_km_h": None if wind is None else round(wind, 1),
        "wind_direction_deg": None if direction is None else round(direction),
        "wind_direction_text": wind_direction_text(direction),
        "precipitation_mm": None if rain is None else round(rain, 1),
        "grid_latitude": _number(location.get("latitude")),
        "grid_longitude": _number(location.get("longitude")),
        "elevation_m": _number(location.get("elevation")),
    }


def _fetch_batch(getter: Getter, url: str, coords, day: date) -> list[dict] | None:
    try:
        status, body = getter(*_request(url, coords, day))
        if status != 200:
            return None
        parsed = json.loads(body)
    except Exception:  # network failure or a malformed provider reply
        return None
    locations = parsed if isinstance(parsed, list) else [parsed]
    if len(locations) != len(coords) or not all(isinstance(item, dict) for item in locations):
        return None
    return locations


def _summary(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "mean": round(statistics.fmean(values), 1),
    }


def build_hotspot_conditions(points: list[dict], getter: Getter, *, today: date | None = None) -> dict:
    """Weather for each hotspot at its own location and pass hour.

    ``points`` are dicts with ``id``, ``lat``, ``lon``, ``acq_date`` and ``acq_time``
    (FIRMS UTC values). The reply lists every point in request order.
    """

    today = today or datetime.now(timezone.utc).date()
    results: list[dict] = []
    # (url, utc day) -> unique rounded coordinates -> result indexes waiting on them
    groups: dict[tuple[str, date], dict[tuple[float, float], list[int]]] = {}
    hour_keys: dict[int, str] = {}
    for index, point in enumerate(points[:MAX_POINTS]):
        point_id = point.get("id", index)
        lat = _number(point.get("lat"))
        lon = _number(point.get("lon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            results.append(_empty(point_id, lat, lon, "invalid_location"))
            continue
        stamp = pass_hour_utc(point.get("acq_date"), point.get("acq_time"))
        if stamp is None:
            results.append(_empty(point_id, lat, lon, "missing_time"))
            continue
        valid_time = stamp.strftime("%Y-%m-%dT%H:%MZ")
        results.append(_empty(point_id, lat, lon, "unavailable", valid_time))
        day = stamp.date()
        if day > today:
            results[-1]["status"] = "future"
            continue
        url = FORECAST_URL if (today - day).days <= FORECAST_PAST_DAYS else ARCHIVE_URL
        coords = (round(lat, 4), round(lon, 4))
        groups.setdefault((url, day), {}).setdefault(coords, []).append(index)
        hour_keys[index] = stamp.strftime("%Y-%m-%dT%H")

    jobs = []
    for (url, day), by_coord in groups.items():
        coords = list(by_coord)
        for start in range(0, len(coords), BATCH_SIZE):
            chunk = coords[start:start + BATCH_SIZE]
            jobs.append((url, day, chunk, [by_coord[item] for item in chunk]))

    def run(job):
        url, day, chunk, waiting = job
        return job, _fetch_batch(getter, url, chunk, day)

    if jobs:
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(jobs)), thread_name_prefix="hotspot-wx") as pool:
            replies = list(pool.map(run, jobs))
    else:
        replies = []

    for (url, _day, _chunk, waiting), locations in replies:
        if locations is None:
            continue
        for location, indexes in zip(locations, waiting):
            for index in indexes:
                reading = _read_location(location, hour_keys[index])
                if reading is None:
                    results[index]["status"] = "missing"
                    continue
                results[index].update(reading)
                results[index]["status"] = "ok" if reading["air_temperature_c"] is not None else "missing"
                results[index]["source"] = "ERA5 archive" if url == ARCHIVE_URL else "Open-Meteo forecast"

    ok = [row for row in results if row["status"] == "ok"]
    return {
        "ok": bool(ok),
        "source": SOURCE,
        "basis": (
            "Weather-model value at the grid point nearest each hotspot, at the UTC hour "
            "nearest its satellite pass. Not the boundary centre."
        ),
        "requested": len(points),
        "answered": len(ok),
        "truncated": len(points) > MAX_POINTS,
        "points": results,
        "summary": {
            "air_temperature_c": _summary([row["air_temperature_c"] for row in ok]),
            "relative_humidity_percent": _summary(
                [row["relative_humidity_percent"] for row in ok if row["relative_humidity_percent"] is not None]
            ),
            "wind_speed_km_h": _summary(
                [row["wind_speed_km_h"] for row in ok if row["wind_speed_km_h"] is not None]
            ),
        },
    }
