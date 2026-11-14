"""Meteomatics point weather and FAO-56 vapour-pressure deficit (air dryness).

Credentials stay in METEOMATICS_USERNAME / METEOMATICS_PASSWORD. They are never
returned to the browser, written into request URLs shown to users, or logged.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote

from app.db import ResponseCache
from vela.network import retrying_get
from vela.settings import DATA_DIR

LOGGER = logging.getLogger(__name__)
SOURCE = "Meteomatics"
BASE_URL = "https://api.meteomatics.com"
FAO56_URL = "https://www.fao.org/4/x0490e/x0490e00.htm"
REQUIRED_PARAMETERS = ("t_2m:C", "relative_humidity_2m:p")
OPTIONAL_PARAMETERS = ("wind_speed_10m:kmh", "wind_dir_10m:d", "precip_24h:mm")
PARAMETER_LABELS = {
    "t_2m:C": "temperature_c",
    "relative_humidity_2m:p": "relative_humidity_percent",
    "wind_speed_10m:kmh": "wind_speed_kmh",
    "wind_dir_10m:d": "wind_dir_deg",
    "precip_24h:mm": "precip_24h_mm",
}
CACHE_KIND = "meteomatics"
CACHE_MAX_AGE_HOURS = 1.0


def credentials_configured() -> bool:
    return bool(os.environ.get("METEOMATICS_USERNAME") and os.environ.get("METEOMATICS_PASSWORD"))


def saturation_vapour_pressure_kpa(temperature_c: float) -> float:
    """FAO-56 Tetens saturation vapour pressure in kilopascals."""

    return 0.6108 * math.exp((17.27 * temperature_c) / (temperature_c + 237.3))


def vapour_pressure_deficit_kpa(temperature_c: float | None, relative_humidity_percent: float | None) -> dict:
    """Air dryness from one time-matched temperature and relative humidity pair.

    A genuine zero is preserved. Missing or non-finite inputs leave dryness
    unavailable without inventing a substitute value.
    """

    if temperature_c is None or relative_humidity_percent is None:
        return {
            "status": "unavailable",
            "vpd_kPa": None,
            "saturation_kPa": None,
            "reason": "Temperature and relative humidity from the same valid time are both required.",
        }
    try:
        temperature = float(temperature_c)
        humidity = float(relative_humidity_percent)
    except (TypeError, ValueError):
        return {
            "status": "unavailable",
            "vpd_kPa": None,
            "saturation_kPa": None,
            "reason": "Temperature and relative humidity must be finite numbers.",
        }
    if not math.isfinite(temperature) or not math.isfinite(humidity):
        return {
            "status": "unavailable",
            "vpd_kPa": None,
            "saturation_kPa": None,
            "reason": "Temperature and relative humidity must be finite numbers.",
        }
    saturation = saturation_vapour_pressure_kpa(temperature)
    deficit = saturation * (1.0 - humidity / 100.0)
    return {
        "status": "ok",
        "vpd_kPa": round(deficit, 2) if deficit != 0 else 0.0,
        "saturation_kPa": round(saturation, 4),
        "reason": None,
    }


def _hour_bucket(valid_time: datetime) -> str:
    stamp = valid_time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return stamp.strftime("%Y-%m-%dT%H:00:00Z")


def _cache_key(latitude: float, longitude: float, valid_hour: str, parameters: tuple[str, ...]) -> str:
    return "|".join(
        [
            f"{latitude:.4f}",
            f"{longitude:.4f}",
            valid_hour,
            ",".join(parameters),
        ]
    )


def _parse_parameter_map(payload: dict) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for entry in payload.get("data") or []:
        name = entry.get("parameter")
        if not name:
            continue
        coordinates = entry.get("coordinates") or []
        if not coordinates:
            values[name] = None
            continue
        dates = coordinates[0].get("dates") or []
        if not dates:
            values[name] = None
            continue
        raw = dates[0].get("value")
        if raw is None:
            values[name] = None
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            values[name] = None
            continue
        values[name] = number if math.isfinite(number) else None
    return values


def _classify_valid_time(valid_time: datetime, now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if valid_time.tzinfo is None:
        valid_time = valid_time.replace(tzinfo=timezone.utc)
    delta_hours = (valid_time - moment).total_seconds() / 3600.0
    if delta_hours < -12:
        return "historical"
    if delta_hours > 12:
        return "forecast"
    return "current"


def _reading(value: float | None, unit: str, status: str = "ok") -> dict:
    if value is None:
        return {"value": None, "unit": unit, "status": "missing"}
    return {"value": value, "unit": unit, "status": status}


def empty_weather(reason: str, *, fixture: bool = False) -> dict:
    return {
        "ok": False,
        "label": "Weather near the selected point",
        "source": SOURCE,
        "configured": credentials_configured(),
        "fixture": fixture,
        "reason": reason,
        "valid_time": None,
        "kind": None,
        "temperature_c": _reading(None, "°C"),
        "relative_humidity_percent": _reading(None, "%"),
        "air_dryness": vapour_pressure_deficit_kpa(None, None),
        "wind_speed_kmh": _reading(None, "km/h"),
        "wind_dir_deg": _reading(None, "°"),
        "precip_24h_mm": _reading(None, "mm"),
        "precip_accumulation_period": "24 hours ending at the weather valid time",
        "optional_denied": [],
        "fields_returned": [],
        "calculation": {
            "title": "How is this calculated?",
            "text": (
                "This combines temperature and humidity. "
                "A higher value means the air has greater drying potential."
            ),
            "method": "FAO-56",
            "url": FAO56_URL,
        },
    }


def weather_from_values(
    *,
    latitude: float,
    longitude: float,
    valid_time: str,
    temperature_c: float | None,
    relative_humidity_percent: float | None,
    wind_speed_kmh: float | None = None,
    wind_dir_deg: float | None = None,
    precip_24h_mm: float | None = None,
    optional_denied: list[str] | None = None,
    fixture: bool = False,
    kind: str | None = None,
) -> dict:
    dryness = vapour_pressure_deficit_kpa(temperature_c, relative_humidity_percent)
    fields = []
    if temperature_c is not None:
        fields.append("temperature_c")
    if relative_humidity_percent is not None:
        fields.append("relative_humidity_percent")
    if wind_speed_kmh is not None:
        fields.append("wind_speed_kmh")
    if wind_dir_deg is not None:
        fields.append("wind_dir_deg")
    if precip_24h_mm is not None:
        fields.append("precip_24h_mm")
    stamp = datetime.fromisoformat(valid_time.replace("Z", "+00:00"))
    return {
        "ok": temperature_c is not None or relative_humidity_percent is not None,
        "label": "Weather near the selected point",
        "source": SOURCE,
        "configured": credentials_configured() or fixture,
        "fixture": fixture,
        "reason": None if (temperature_c is not None or relative_humidity_percent is not None) else "No weather values available.",
        "valid_time": stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind or _classify_valid_time(stamp),
        "point": {"latitude": latitude, "longitude": longitude},
        "temperature_c": _reading(temperature_c, "°C"),
        "relative_humidity_percent": _reading(relative_humidity_percent, "%"),
        "air_dryness": dryness,
        "wind_speed_kmh": _reading(wind_speed_kmh, "km/h"),
        "wind_dir_deg": _reading(wind_dir_deg, "°"),
        "precip_24h_mm": _reading(precip_24h_mm, "mm"),
        "precip_accumulation_period": "24 hours ending at the weather valid time",
        "optional_denied": list(optional_denied or []),
        "fields_returned": fields,
        "calculation": {
            "title": "How is this calculated?",
            "text": (
                "This combines temperature and humidity. "
                "A higher value means the air has greater drying potential."
            ),
            "method": "FAO-56",
            "url": FAO56_URL,
        },
    }


class MeteomaticsClient:
    """Server-side Meteomatics client with hour-bucketed response reuse."""

    def __init__(
        self,
        cache: ResponseCache | None = None,
        http_get: Callable[[str, tuple[str, str]], tuple[int, str]] | None = None,
    ):
        self.cache = cache or ResponseCache(DATA_DIR / "cache" / "meteomatics.sqlite")
        self.http_get = http_get or self._default_get

    @staticmethod
    def _default_get(url: str, auth: tuple[str, str]) -> tuple[int, str]:
        response = retrying_get(url, auth=auth, timeout=30.0)
        return response.status_code, response.text

    def fetch_point(
        self,
        latitude: float,
        longitude: float,
        valid_time: datetime | str | None = None,
        *,
        include_optional: bool = True,
    ) -> dict:
        if not credentials_configured():
            return empty_weather(
                "Meteomatics credentials are not configured. "
                "Set METEOMATICS_USERNAME and METEOMATICS_PASSWORD in the server .env."
            )

        if valid_time is None:
            stamp = datetime.now(timezone.utc)
        elif isinstance(valid_time, str):
            stamp = datetime.fromisoformat(valid_time.replace("Z", "+00:00"))
        else:
            stamp = valid_time
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)

        valid_hour = _hour_bucket(stamp)
        required = REQUIRED_PARAMETERS
        optional = OPTIONAL_PARAMETERS if include_optional else ()
        username = os.environ["METEOMATICS_USERNAME"]
        password = os.environ["METEOMATICS_PASSWORD"]
        auth = (username, password)

        values: dict[str, float | None] = {}
        optional_denied: list[str] = []

        # Prefer one request with every parameter; fall back if optional fields are denied.
        parameter_sets = [required + optional] if optional else [required]
        if optional:
            parameter_sets.append(required)

        last_error = None
        for parameters in parameter_sets:
            key = _cache_key(latitude, longitude, valid_hour, parameters)
            cached = self.cache.get(key, max_age_hours=CACHE_MAX_AGE_HOURS)
            if cached is not None:
                payload = json.loads(cached)
                values = _parse_parameter_map(payload)
                break
            url = (
                f"{BASE_URL}/{quote(valid_hour, safe='')}/"
                f"{','.join(parameters)}/"
                f"{latitude:.5f},{longitude:.5f}/json"
            )
            try:
                status, body = self.http_get(url, auth)
            except Exception as exc:  # noqa: BLE001 — keep satellite findings visible on weather failure
                LOGGER.warning("Meteomatics request failed without exposing credentials.")
                last_error = "Weather request failed."
                continue
            if status == 200:
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    last_error = "Weather response could not be parsed."
                    continue
                self.cache.put(key, CACHE_KIND, body)
                values = _parse_parameter_map(payload)
                break
            if status in {400, 403} and parameters != required:
                optional_denied = [PARAMETER_LABELS[name] for name in optional]
                last_error = "Optional weather fields were denied by the active plan."
                continue
            last_error = "Weather request was refused or unavailable."
            LOGGER.warning("Meteomatics returned HTTP %s without exposing credentials.", status)

        if not values:
            return empty_weather(last_error or "Weather unavailable.")

        denied = []
        for name in optional:
            label = PARAMETER_LABELS[name]
            if name not in values or values.get(name) is None:
                if label not in denied:
                    denied.append(label)
        if optional_denied:
            denied = sorted(set(denied + optional_denied))

        return weather_from_values(
            latitude=latitude,
            longitude=longitude,
            valid_time=valid_hour,
            temperature_c=values.get("t_2m:C"),
            relative_humidity_percent=values.get("relative_humidity_2m:p"),
            wind_speed_kmh=values.get("wind_speed_10m:kmh"),
            wind_dir_deg=values.get("wind_dir_10m:d"),
            precip_24h_mm=values.get("precip_24h:mm"),
            optional_denied=denied,
            fixture=False,
        )
