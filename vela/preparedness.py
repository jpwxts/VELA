"""Seven-day weather and the published GWIS Fire Weather Index."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from vela.forecast_store import ForecastArchive
from vela.geotiff import read_center_value
from vela.settings import DATA_DIR

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GWIS_WMS = "https://maps.effis.emergency.copernicus.eu/gwis"
FWI_LAYER = "ecmwf.fwi"
RANKING_LAYER = "ecmwf.ranking"
FWI_SOURCE = (
    "Copernicus Emergency Management Service, GWIS. "
    "ECMWF Fire Weather Index from WMS layer ecmwf.fwi."
)
RANKING_SOURCE = (
    "Copernicus Emergency Management Service, GWIS. "
    "ECMWF local historical FWI ranking from WMS layer ecmwf.ranking."
)
WEATHER_SOURCE = "Open-Meteo forecast API"
DAILY_FIELDS = (
    "temperature_2m_max",
    "relative_humidity_2m_min",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "precipitation_sum",
)
ASMC_FWI_MAP = "https://asmc.asean.org/asmc-fire-fwi/"
ASMC_FDRS_OVERVIEW = "https://asmc.asean.org/asmc-fire/"
ASMC_REFERENCE = {
    "name": "ASMC Fire Weather Index map",
    "producer": "ASEAN Specialised Meteorological Centre / Malaysian Meteorological Department",
    "url": ASMC_FWI_MAP,
    "overview_url": ASMC_FDRS_OVERVIEW,
    "access": "regional_map_reference",
    "note": (
        "ASMC publishes a Southeast Asia Fire Weather Index map (image courtesy of the "
        "Malaysian Meteorological Department). Vela links that map as a regional reference "
        "and does not read numbers from map colors."
    ),
}


def forecast_point(west: float, south: float, east: float, north: float) -> tuple[float, float]:
    """Center of the selected box. A date-line box is averaged across 180."""

    if west <= east:
        longitude = (west + east) / 2
    else:
        longitude = ((west + 360) + east) / 2
        if longitude > 180:
            longitude -= 360
    return (south + north) / 2, longitude


def region_key(west: float, south: float, east: float, north: float) -> str:
    values = [round(float(item), 2) for item in (west, south, east, north)]
    return ",".join(f"{item:.2f}" for item in values)


def verification_status(report: dict | None) -> dict:
    """Held-out weekly error only. In-sample pilot diagnostics are not a score."""

    validation = (report or {}).get("validation")
    measured = []
    if isinstance(validation, dict):
        for name, score in validation.items():
            if not isinstance(score, dict):
                continue
            error = score.get("weekly_mae_percentage_points")
            if isinstance(error, (int, float)):
                measured.append((name, float(error)))
    if not measured:
        return {
            "status": "pending_verification",
            "held_out_error_percentage_points": None,
            "model": None,
            "text": "Pending verification. No held-out harmonization error has been measured.",
        }
    chosen = (report or {}).get("chosen_model")
    picked = next((item for item in measured if item[0] == chosen), measured[0])
    return {
        "status": "measured",
        "held_out_error_percentage_points": picked[1],
        "model": picked[0],
        "text": (
            f"Held-out weekly error for {picked[0].replace('_', ' ')}: "
            f"{picked[1]:.2f} percentage points."
        ),
    }


def parse_weather(payload: dict) -> dict:
    daily = payload.get("daily") or {}
    times = list(daily.get("time") or [])
    if len(times) < 2 or len(times) % 2:
        return {"ok": False, "status": "missing", "message": "The weather feed did not return a seven-day window."}
    half = len(times) // 2
    required = (
        "temperature_2m_max",
        "relative_humidity_2m_min",
        "wind_speed_10m_max",
        "wind_gusts_10m_max",
        "precipitation_sum",
    )
    columns = {name: list(daily.get(name) or []) for name in DAILY_FIELDS}
    if any(len(columns[name]) != len(times) for name in required):
        return {"ok": False, "status": "missing", "message": "The weather feed left out a daily field."}
    if len(columns["wind_direction_10m_dominant"]) != len(times):
        columns["wind_direction_10m_dominant"] = [None] * len(times)
    past = [_rain(columns["precipitation_sum"][index]) for index in range(half)]
    if any(item is None for item in past):
        recent = {"status": "missing", "millimetres": None}
    else:
        total = round(float(sum(past)), 1)
        recent = {
            "status": "quiet" if total == 0 else "measured",
            "millimetres": total,
            "days": half,
            "start": times[0],
            "end": times[half - 1],
        }
    days = []
    anchor = date.fromisoformat(times[half])
    for index, valid in enumerate(times[half:]):
        offset = half + index
        values = {name: _number(columns[name][offset]) for name in DAILY_FIELDS}
        valid_day = date.fromisoformat(valid)
        wind_ms = _field(values["wind_speed_10m_max"])
        gust_ms = _field(values["wind_gusts_10m_max"])
        direction = _number(values["wind_direction_10m_dominant"])
        days.append(
            {
                "valid_date": valid,
                "lead_days": (valid_day - anchor).days,
                "temperature_max_c": _field(values["temperature_2m_max"]),
                "relative_humidity_min_percent": _field(values["relative_humidity_2m_min"]),
                "wind_speed_max_m_s": wind_ms,
                "wind_speed_max_km_h": _ms_to_kmh_field(wind_ms),
                "wind_gust_max_m_s": gust_ms,
                "wind_gust_max_km_h": _ms_to_kmh_field(gust_ms),
                "wind_direction_deg": (
                    {"status": "measured", "value": direction}
                    if direction is not None
                    else {"status": "missing", "value": None}
                ),
                "wind_direction_text": wind_direction_text(direction),
                "forecast_rain_mm": _field(values["precipitation_sum"]),
                "rain_period": "daily total (local calendar day)",
                "wind_period": "daily maximum sustained 10 m wind",
                "gust_period": "daily maximum 10 m gust",
                "temperature_period": "daily maximum 2 m air temperature",
                "humidity_period": "daily minimum 2 m relative humidity",
                "verification_status": "pending",
            }
        )
    forecast_rain = [day["forecast_rain_mm"]["value"] for day in days]
    if any(value is None for value in forecast_rain):
        forecast_total = {"status": "missing", "millimetres": None}
    else:
        total = round(float(sum(forecast_rain)), 1)
        forecast_total = {"status": "quiet" if total == 0 else "measured", "millimetres": total}
    return {
        "ok": True,
        "status": "measured",
        "source": WEATHER_SOURCE,
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "timezone": payload.get("timezone"),
        "recent_rain": recent,
        "forecast_rain": forecast_total,
        "days": days,
    }


def wind_direction_text(degrees) -> str | None:
    """Compass wording such as 'from the northeast' for a meteorological from-direction."""

    if degrees is None:
        return None
    try:
        bearing = float(degrees) % 360
    except (TypeError, ValueError):
        return None
    labels = (
        "north",
        "northeast",
        "east",
        "southeast",
        "south",
        "southwest",
        "west",
        "northwest",
    )
    index = int((bearing + 22.5) // 45) % 8
    return f"from the {labels[index]}"


def explain_day(day: dict) -> str:
    wind_kmh = day.get("wind_speed_max_km_h") or _ms_to_kmh_field(day.get("wind_speed_max_m_s") or {})
    gust_kmh = day.get("wind_gust_max_km_h") or _ms_to_kmh_field(day.get("wind_gust_max_m_s") or {})
    sentences = [
        _measure("Maximum air temperature", day.get("temperature_max_c") or {}, "°C"),
        _measure("Minimum relative humidity", day.get("relative_humidity_min_percent") or {}, "%"),
        _measure("Sustained wind", wind_kmh, "km/h"),
    ]
    direction = day.get("wind_direction_text") or wind_direction_text(
        (day.get("wind_direction_deg") or {}).get("value")
    )
    if direction:
        sentences.append(f"Wind is {direction}.")
    if gust_kmh.get("status") in {"measured", "quiet"} and gust_kmh.get("value") is not None:
        sentences.append(_measure("Wind gusts", gust_kmh, "km/h"))
    sentences.append(
        _measure("Forecast rainfall", day.get("forecast_rain_mm") or {}, "mm", quiet_zero=True)
    )
    fire = day.get("fire_danger") or {}
    if fire.get("status") == "measured" and fire.get("fwi") is not None:
        sentences.append(f"The published GWIS Fire Weather Index for this date is {fire['fwi']:.1f}.")
        if fire.get("ranking") is not None:
            sentences.append(
                f"The published local historical ranking is {fire['ranking']:.1f} "
                "on the GWIS percentile scale."
            )
    else:
        sentences.append("Fire-danger rating unavailable for this day.")
    return " ".join(sentences)


def draft_brief(forecast: dict, day: dict, hotspots: dict) -> str:
    point = forecast.get("point") or {}
    fire = day.get("fire_danger") or {}
    lines = [
        "Vela preparedness brief",
        "This draft is for review before it is sent to the configured test inbox.",
        f"Forecast point: {point.get('latitude')}, {point.get('longitude')}.",
        f"Valid local date: {day['valid_date']}. Lead time: {day['lead_days']} day(s).",
        explain_day(day),
        f"Recent accumulated rainfall: {_rain_phrase(forecast.get('recent_rain') or {})}.",
        f"Forecast rainfall over the seven days: {_rain_phrase(forecast.get('forecast_rain') or {})}.",
        f"Fire Weather Index source: {fire.get('source') or 'unavailable'}",
        f"FWI valid date: {fire.get('valid_date') or day['valid_date']}.",
        f"FWI product issue time: {fire.get('issue_time') or 'unavailable'}.",
        f"NASA hotspot observations: {_hotspot_phrase(hotspots)}",
        forecast.get("performance", {}).get("text")
        or "Pending verification. No held-out harmonization error has been measured.",
        "The harmonization error is reported in percentage points of usable cell-days when a held-out score exists.",
    ]
    return "\n".join(lines)


def weather_request(latitude: float, longitude: float) -> tuple[str, dict]:
    return OPEN_METEO, {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join(DAILY_FIELDS),
        "timezone": "auto",
        "forecast_days": 7,
        "past_days": 7,
        "wind_speed_unit": "ms",
    }


def gwis_request(layer: str, latitude: float, longitude: float, valid_date: str) -> tuple[str, dict]:
    span = 0.12
    return GWIS_WMS, {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "SRS": "EPSG:4326",
        "BBOX": f"{longitude - span},{latitude - span},{longitude + span},{latitude + span}",
        "WIDTH": 3,
        "HEIGHT": 3,
        "FORMAT": "image/tiff",
        "TRANSPARENT": "false",
        "TIME": valid_date,
    }


def build_forecast(west: float, south: float, east: float, north: float, getter, report: dict | None = None) -> dict:
    latitude, longitude = forecast_point(west, south, east, north)
    performance = verification_status(report)
    url, params = weather_request(latitude, longitude)
    status, body = getter(url, params)
    if status != 200:
        return _failed(latitude, longitude, performance, "The weather feed did not respond.")
    try:
        parsed = parse_weather(json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return _failed(latitude, longitude, performance, "The weather feed could not be read.")
    if not parsed.get("ok"):
        return _failed(latitude, longitude, performance, parsed.get("message") or "Weather details are missing.")
    point_lat = parsed.get("latitude") if isinstance(parsed.get("latitude"), (int, float)) else latitude
    point_lon = parsed.get("longitude") if isinstance(parsed.get("longitude"), (int, float)) else longitude
    for day in parsed["days"]:
        day["fire_danger"] = _fire_danger(getter, float(point_lat), float(point_lon), day["valid_date"])
    window = f"{parsed['days'][0]['valid_date']}:{parsed['days'][-1]['valid_date']}"
    key = region_key(west, south, east, north)
    issue_id = f"gwis-ecmwf|{key}|{window}"
    return {
        "ok": True,
        "issue_id": issue_id,
        "region_key": key,
        "point": {
            "latitude": point_lat,
            "longitude": point_lon,
            "timezone": parsed.get("timezone"),
            "label": "Weather near the center of your selection.",
        },
        "weather_source": WEATHER_SOURCE,
        "fwi_source": FWI_SOURCE,
        "ranking_source": RANKING_SOURCE,
        "recent_rain": parsed["recent_rain"],
        "forecast_rain": parsed["forecast_rain"],
        "days": parsed["days"],
        "performance": performance,
        "product_issue_time": None,
        "product_issue_status": "missing",
        "regional_fwi_reference": regional_fwi_reference(west, south, east, north),
    }


def issue_forecast(archive: ForecastArchive, forecast: dict) -> dict:
    if not forecast.get("ok"):
        return forecast
    stored = archive.put_if_absent(forecast["issue_id"], forecast["region_key"], forecast)
    stored["ok"] = True
    return stored


def _fire_danger(getter, latitude: float, longitude: float, valid_date: str) -> dict:
    fwi = _layer_value(getter, FWI_LAYER, latitude, longitude, valid_date)
    ranking = _layer_value(getter, RANKING_LAYER, latitude, longitude, valid_date)
    if fwi is None or not 0 <= fwi <= 200:
        return {
            "status": "unavailable",
            "fwi": None,
            "ranking": ranking if ranking is not None and 0 <= ranking <= 100 else None,
            "source": FWI_SOURCE,
            "ranking_source": RANKING_SOURCE,
            "valid_date": valid_date,
            "issue_time": None,
        }
    return {
        "status": "measured",
        "fwi": fwi,
        "ranking": ranking if ranking is not None and 0 <= ranking <= 100 else None,
        "source": FWI_SOURCE,
        "ranking_source": RANKING_SOURCE,
        "valid_date": valid_date,
        "issue_time": None,
    }


def _layer_value(getter, layer: str, latitude: float, longitude: float, valid_date: str) -> float | None:
    url, params = gwis_request(layer, latitude, longitude, valid_date)
    try:
        status, body = getter(url, params)
    except Exception:
        return None
    if status != 200:
        return None
    return read_center_value(body)


def _failed(latitude: float, longitude: float, performance: dict, message: str) -> dict:
    return {
        "ok": False,
        "status": "missing",
        "message": message,
        "point": {"latitude": latitude, "longitude": longitude, "timezone": None, "label": message},
        "days": [],
        "recent_rain": {"status": "missing", "millimetres": None},
        "forecast_rain": {"status": "missing", "millimetres": None},
        "performance": performance,
        "product_issue_time": None,
        "product_issue_status": "missing",
    }


def _number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _rain(value):
    return _number(value)


def _field(value) -> dict:
    if value is None:
        return {"status": "missing", "value": None}
    if value == 0:
        return {"status": "quiet", "value": 0.0}
    return {"status": "measured", "value": value}


def _ms_to_kmh_field(field: dict | None) -> dict:
    if not field or field.get("status") == "missing" or field.get("value") is None:
        return {"status": "missing", "value": None}
    return {
        "status": field.get("status") or "measured",
        "value": round(float(field["value"]) * 3.6, 1),
    }


def regional_fwi_reference(west: float, south: float, east: float, north: float) -> dict | None:
    """Documented regional FWI map for selections that overlap Southeast Asia."""

    lat, lon = forecast_point(west, south, east, north)
    # Rough ASEAN / Philippines window where ASMC FDRS maps are relevant.
    if 5.0 <= lat <= 21.5 and 116.0 <= lon <= 127.0:
        return dict(ASMC_REFERENCE)
    if -11.0 <= lat <= 28.0 and 92.0 <= lon <= 141.0:
        return dict(ASMC_REFERENCE)
    return None


def request_bytes(url: str, params: dict | None = None) -> tuple[int, bytes]:
    import httpx

    # GWIS EFFIS WMS currently serves an expired TLS certificate; verify is
    # disabled only for that known host so FWI GeoTIFF reads can continue.
    verify = True
    if "maps.effis.emergency.copernicus.eu" in url:
        verify = False
    with httpx.Client(timeout=40.0, follow_redirects=True, verify=verify) as client:
        response = client.get(url, params=params)
        return response.status_code, response.content


def _measure(label: str, field: dict, unit: str, quiet_zero: bool = False) -> str:
    if not field or field.get("status") == "missing" or field.get("value") is None:
        return f"{label} is missing."
    if quiet_zero and field.get("status") == "quiet":
        return f"{label} is 0 {unit}. That is a quiet observation, not missing data."
    return f"{label} is {field['value']:.1f} {unit}."


def _rain_phrase(field: dict) -> str:
    if field.get("status") == "missing" or field.get("millimetres") is None:
        return "missing"
    if field.get("status") == "quiet":
        return "0 mm, a quiet observation"
    return f"{field['millimetres']:.1f} mm"


def _hotspot_phrase(hotspots: dict) -> str:
    status = hotspots.get("observation_status")
    if status == "missing":
        return hotspots.get("message") or "Missing."
    if status == "no_hotspots":
        return (
            f"No hotspots returned for {hotspots.get('date')}. "
            "FIRMS lists detections only, and coverage is unknown."
        )
    count = hotspots.get("total_count")
    return f"{count} detection(s) on {hotspots.get('date')}. Coverage is unknown."


def load_model_report(path: Path | None = None) -> dict:
    report_path = path or (DATA_DIR / "models" / "report.json")
    if not report_path.is_file():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))

