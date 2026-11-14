"""NASA FIRMS area client. Requests stay on the server and the map key stays out of logs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from datetime import date, datetime, timezone

from app.db import ResponseCache
from vela.geo import firms_boxes, format_hhmm, lon_span, round_box

logger = logging.getLogger("vela.firms")

AREA_ROOT = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
AVAILABILITY_ROOT = "https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv"

SATELLITE_LABELS = {
    "A": "Aqua",
    "AQUA": "Aqua",
    "T": "Terra",
    "TERRA": "Terra",
    "N": "Suomi-NPP",
    "NPP": "Suomi-NPP",
    "SNPP": "Suomi-NPP",
    "SUOMI-NPP": "Suomi-NPP",
    "SUOMI NPP": "Suomi-NPP",
    "N20": "NOAA-20",
    "NOAA-20": "NOAA-20",
    "NOAA20": "NOAA-20",
    "N21": "NOAA-21",
    "NOAA-21": "NOAA-21",
    "NOAA21": "NOAA-21",
}

PRODUCTS = {
    "Aqua": ("MODIS_SP", "MODIS_NRT"),
    "Terra": ("MODIS_SP", "MODIS_NRT"),
    "Suomi-NPP": ("VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
    "NOAA-20": ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"),
    "NOAA-21": ("VIIRS_NOAA21_SP", "VIIRS_NOAA21_NRT"),
}

PLATFORM_ORDER = ("Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21")


def redact(text: str, key: str = "") -> str:
    cleaned = text or ""
    if key:
        cleaned = cleaned.replace(key, "[REDACTED]")
    cleaned = re.sub(r"/api/area/csv/[^/\s]+/", "/api/area/csv/[REDACTED]/", cleaned)
    cleaned = re.sub(
        r"/api/data_availability/csv/[^/\s]+/",
        "/api/data_availability/csv/[REDACTED]/",
        cleaned,
    )
    cleaned = re.sub(r"MAP_KEY=[^&\s]+", "MAP_KEY=[REDACTED]", cleaned)
    return cleaned[:300]


def platform_name(satellite: str) -> str | None:
    return SATELLITE_LABELS.get(str(satellite).strip().upper())


def _cache_key(kind: str, product: str, day: str, box) -> str:
    raw = "|".join([kind, product, day, *(f"{value:.4f}" for value in box)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _float(value):
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_hotspots(text: str) -> list[dict]:
    sample = text.lstrip("\ufeff").strip()
    if not sample:
        return []
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        return []
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    hotspots = []
    for row in reader:
        if not row.get("latitude") or not row.get("longitude"):
            continue
        satellite = str(row.get("satellite", "")).strip()
        instrument = str(row.get("instrument", "")).strip() or "unknown"
        brightness = row.get("brightness", row.get("bright_ti4", ""))
        hotspots.append(
            {
                "lat": float(row["latitude"]),
                "lon": float(row["longitude"]),
                "acq_date": str(row.get("acq_date", "")).strip(),
                "acq_time": format_hhmm(row.get("acq_time", "")),
                "acq_time_raw": str(row.get("acq_time", "")).strip(),
                "satellite_code": satellite,
                "platform": platform_name(satellite) or satellite or "Unrecognized",
                "instrument": instrument,
                "confidence": str(row.get("confidence", "")).strip(),
                "frp": _float(row.get("frp", "")),
                "daynight": str(row.get("daynight", "")).strip(),
                "brightness": _float(brightness),
                "version": str(row.get("version", "")).strip(),
            }
        )
    return hotspots


def parse_availability(text: str) -> dict[str, tuple[date, date]]:
    sample = text.lstrip("\ufeff").strip()
    reader = csv.DictReader(io.StringIO(sample))
    if not reader.fieldnames:
        return {}
    reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    parsed = {}
    for row in reader:
        product = (row.get("data_id") or "").strip()
        try:
            parsed[product] = (
                datetime.strptime(row["min_date"], "%Y-%m-%d").date(),
                datetime.strptime(row["max_date"], "%Y-%m-%d").date(),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


def choose_processing(day: date, spans: dict[str, tuple[date, date]], standard: str, near: str):
    standard_span = spans.get(standard)
    near_span = spans.get(near)
    if standard_span and standard_span[0] <= day <= standard_span[1]:
        return standard, "standard"
    if near_span and near_span[0] <= day <= near_span[1]:
        return near, "near_real_time"
    return None, None


def _looks_like_csv(text: str) -> bool:
    first = text.lstrip("\ufeff").strip().splitlines()[:1]
    if not first:
        return False
    header = first[0].lower()
    return "latitude" in header and "longitude" in header


class FirmsClient:
    def __init__(self, key: str, cache: ResponseCache, getter, max_span: float = 30, day_range: int = 1):
        self.key = (key or "").strip()
        self.cache = cache
        self.getter = getter
        self.max_span = max_span
        self.day_range = min(5, max(1, int(day_range)))

    def hotspots(self, west: float, south: float, east: float, north: float, day: str, platforms: list[str]) -> dict:
        west, south, east, north = round_box(west, south, east, north)
        requested = [name for name in PLATFORM_ORDER if name in platforms] or list(platforms)
        box = {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
            "crossed_dateline": west > east,
        }
        if not self.key:
            message = (
                "FIRMS_MAP_KEY is not set. Each developer needs a free NASA FIRMS map key "
                "in their own .env file, then restart Vela. Live satellite search cannot run "
                "from GitHub-trained tables alone. Saved examples still work without a key. "
                "The key itself is not shown here."
            )
            return _with_combined({
                "configured": False,
                "date": day,
                "bbox": box,
                "total_count": 0,
                "results": [
                    {
                        **_status("not_configured", message),
                        "platform": name,
                        "count": 0,
                        "coverage": "unknown",
                    }
                    for name in requested
                ],
            })
        height = float(north) - float(south)
        if lon_span(west, east) > self.max_span or height > self.max_span or height <= 0:
            return _with_combined({
                "configured": True,
                "date": day,
                "bbox": box,
                "total_count": 0,
                "results": [
                    _status(
                        "area_too_large",
                        f"Choose a box smaller than {self.max_span:.0f} degrees on each side, then confirm it.",
                    )
                ],
            })
        try:
            observed = datetime.strptime(day, "%Y-%m-%d").date()
        except ValueError:
            return _with_combined({
                "configured": True,
                "date": day,
                "bbox": box,
                "total_count": 0,
                "results": [_status("request_failed", "Use a date in YYYY-MM-DD form.")],
            })
        availability, availability_error = self._availability()
        if availability_error:
            return _with_combined({
                "configured": True,
                "date": day,
                "bbox": box,
                "total_count": 0,
                "results": [_status("request_failed", availability_error)],
            })
        choices = {}
        for platform in requested:
            if platform not in PRODUCTS:
                choices[platform] = (None, None)
                continue
            choices[platform] = choose_processing(observed, availability, *PRODUCTS[platform])
        fetched = {}
        for product, processing in {(product, processing) for product, processing in choices.values() if product}:
            fetched[(product, processing)] = self._fetch_product(product, processing, (west, south, east, north), day)
        results = []
        total = 0
        reported_unknown = set()
        for platform in requested:
            product, processing = choices[platform]
            if product is None:
                results.append(
                    {
                        **_status("product_unavailable", "The date is outside the standard and near-real-time ranges."),
                        "platform": platform,
                        "coverage": "unknown",
                    }
                )
                continue
            payload = fetched[(product, processing)]
            if payload["status"] == "request_failed":
                results.append(
                    {
                        **_status("request_failed", payload["message"]),
                        "platform": platform,
                        "product": product,
                        "processing": processing,
                        "coverage": "unknown",
                        "cached": payload["cached"],
                    }
                )
                continue
            matched = [item for item in payload["hotspots"] if item["platform"] == platform]
            for item in matched:
                item["source"] = product
            unknown = [
                item
                for item in payload["hotspots"]
                if item["platform"] not in PRODUCTS and product not in reported_unknown
            ]
            status = "no_hotspots" if not matched else "ok"
            message = "No hotspots returned." if status == "no_hotspots" else ""
            results.append(
                {
                    "platform": platform,
                    "product": product,
                    "processing": processing,
                    "status": status,
                    "coverage": "unknown",
                    "count": len(matched),
                    "cached": payload["cached"],
                    "message": message,
                    "hotspots": matched,
                }
            )
            total += len(matched)
            if unknown:
                reported_unknown.add(product)
                results.append(
                    {
                        "platform": "Unrecognized",
                        "product": product,
                        "processing": processing,
                        "status": "ok",
                        "coverage": "unknown",
                        "count": len(unknown),
                        "cached": payload["cached"],
                        "message": "Returned by FIRMS with a satellite code Vela does not recognize.",
                        "hotspots": unknown,
                    }
                )
                total += len(unknown)
        return _with_combined({"configured": True, "date": day, "bbox": box, "total_count": total, "results": results})

    def latest_available_day(self, platforms: list[str], today: date | None = None) -> str | None:
        """Latest date that still falls inside a published FIRMS range."""

        if not self.key:
            return None
        availability, error = self._availability()
        if error or not availability:
            return None
        limit = today or datetime.now(timezone.utc).date()
        ends = []
        for platform in platforms:
            products = PRODUCTS.get(platform)
            if not products:
                continue
            for product in products:
                span = availability.get(product)
                if span and span[0] <= limit:
                    ends.append(min(span[1], limit))
        if not ends:
            return None
        return max(ends).isoformat()

    def _availability(self) -> tuple[dict, str | None]:
        fingerprint = hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:12]
        key = _cache_key("availability", fingerprint, "all", (0, 0, 0, 0))
        cached = self.cache.get(key, max_age_hours=12)
        text = cached
        if text is None:
            url = f"{AVAILABILITY_ROOT}/{self.key}/all"
            try:
                status, text = self.getter(url)
            except Exception as exc:  # noqa: BLE001
                logger.info("FIRMS availability request failed")
                return {}, redact(str(exc), self.key)
            logger.info("FIRMS availability http_status=%s", status)
            if status >= 400 or not text or "data_id" not in text.lower():
                return {}, redact(text or f"HTTP {status}", self.key) or "Availability request failed."
            self.cache.put(key, "availability", text)
        parsed = parse_availability(text)
        if not parsed:
            return {}, "Availability response could not be read."
        return parsed, None

    def _fetch_product(self, product: str, processing: str, box, day: str) -> dict:
        pieces = []
        cached_flags = []
        for piece in firms_boxes(*box):
            key = _cache_key("area", product, day, piece)
            max_age = 3 if processing == "near_real_time" else None
            cached = self.cache.get(key, max_age_hours=max_age)
            if cached is not None:
                body = cached
                cached_flags.append(True)
            else:
                west, south, east, north = piece
                area = f"{west},{south},{east},{north}"
                url = f"{AREA_ROOT}/{self.key}/{product}/{area}/{self.day_range}/{day}"
                try:
                    status, body = self.getter(url)
                except Exception as exc:  # noqa: BLE001
                    logger.info("FIRMS area failed product=%s date=%s", product, day)
                    return {
                        "status": "request_failed",
                        "message": redact(str(exc), self.key) or "Request failed.",
                        "hotspots": [],
                        "cached": False,
                    }
                logger.info(
                    "FIRMS area product=%s date=%s box=%s http_status=%s",
                    product,
                    day,
                    area,
                    status,
                )
                interpreted, message = _interpret(status, body, self.key)
                if interpreted == "request_failed":
                    return {"status": "request_failed", "message": message, "hotspots": [], "cached": False}
                self.cache.put(key, "area", body)
                cached_flags.append(False)
            pieces.append(body)
        hotspots = []
        seen = set()
        for body in pieces:
            for item in parse_hotspots(body):
                identity = (
                    round(item["lat"], 5),
                    round(item["lon"], 5),
                    item["acq_date"],
                    item["acq_time_raw"],
                    item["satellite_code"],
                    item["instrument"],
                )
                if identity in seen:
                    continue
                seen.add(identity)
                hotspots.append(item)
        return {"status": "ok", "message": "", "hotspots": hotspots, "cached": all(cached_flags) and bool(cached_flags)}


def _interpret(status: int, body: str, key: str) -> tuple[str, str]:
    if status >= 400:
        return "request_failed", redact(body, key) or f"HTTP {status}"
    if _looks_like_csv(body):
        return "ok", ""
    lowered = (body or "").lower()
    if "no data" in lowered or not (body or "").strip():
        return "ok", ""
    return "request_failed", redact(body, key) or "Request failed."


def combined_observations(payload: dict) -> dict:
    """Summarize the satellite feeds without turning unknown coverage into a zero."""

    results = payload.get("results") or []
    feeds = [row for row in results if row.get("platform") in PRODUCTS]
    queried = [row for row in feeds if row.get("status") in {"ok", "no_hotspots"}]
    unavailable = [row for row in feeds if row.get("status") == "product_unavailable"]
    failed = [row for row in feeds if row.get("status") == "request_failed"]
    established = any((row.get("coverage") or "unknown") != "unknown" for row in queried)
    coverage = "established" if established else "unknown"
    label = (
        "Harmonized activity is available from adequately observed cell-days."
        if established
        else "Harmonized activity is unavailable until coverage is established."
    )
    return {
        "raw_detection_records": int(payload.get("total_count") or 0),
        "feeds_queried": len(queried),
        "feeds_unavailable": len(unavailable),
        "feeds_failed": len(failed),
        "coverage": coverage,
        "harmonized_activity": "available" if established else "unavailable",
        "harmonized_activity_label": label,
        "unavailable_platforms": [row.get("platform") for row in unavailable],
        "failed_platforms": [row.get("platform") for row in failed],
    }


def _with_combined(payload: dict) -> dict:
    from vela.hotspot_areas import group_hotspot_areas, public_result_summary

    payload["combined"] = combined_observations(payload)
    payload["hotspot_areas"] = group_hotspot_areas(payload)
    payload["public_result"] = public_result_summary(payload, payload["hotspot_areas"])
    return payload


def _status(status: str, message: str) -> dict:
    return {
        "platform": None,
        "product": None,
        "processing": None,
        "status": status,
        "coverage": "unknown",
        "count": 0,
        "cached": False,
        "message": message,
        "hotspots": [],
    }


def dumps_result(payload: dict) -> str:
    return json.dumps(payload)
