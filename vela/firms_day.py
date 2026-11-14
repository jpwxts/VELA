"""FIRMS retrieval for one Philippine calendar day.

Queries the overlapping UTC dates, clips to the selected polygon, and deduplicates
repeat retrievals without dropping distinct pixels or passes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vela.land_check import classify_detections, point_in_ring, polygon_bbox

MANILA = ZoneInfo("Asia/Manila")
DEFAULT_PLATFORMS = ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"]


def parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def utc_dates_for_ph_day(ph_day: date) -> list[str]:
    """UTC acquisition dates that can fall on a Philippine calendar day (UTC+8)."""

    previous = (ph_day - timedelta(days=1)).isoformat()
    current = ph_day.isoformat()
    return [previous, current]


def ph_day_for_utc(acq_date: str, acq_time: str | None) -> str | None:
    text = str(acq_time or "00:00").strip()
    if ":" in text:
        hour, minute = [int(part) for part in text.split(":", 1)[:2]]
    else:
        digits = "".join(ch for ch in text if ch.isdigit()).zfill(4)[-4:]
        hour, minute = int(digits[:2]), int(digits[2:])
    try:
        stamp = datetime(
            int(acq_date[:4]),
            int(acq_date[5:7]),
            int(acq_date[8:10]),
            hour,
            minute,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return stamp.astimezone(MANILA).date().isoformat()


def _detection_key(row: dict) -> tuple:
    return (
        str(row.get("platform") or ""),
        str(row.get("acq_date") or "")[:10],
        str(row.get("acq_time") or row.get("acq_time_raw") or ""),
        round(float(row.get("lat") or 0), 5),
        round(float(row.get("lon") or 0), 5),
    )


def _feed_row(result: dict, utc_day: str) -> dict:
    status = result.get("status") or "unknown"
    coverage = result.get("coverage")
    count = int(result.get("count") or 0)
    if status in {"request_failed", "not_configured"}:
        outcome = "failed" if status == "request_failed" else "unavailable"
    elif status in {"product_unavailable", "area_too_large"}:
        outcome = "unavailable"
    elif status == "ok" and count == 0:
        outcome = "zero"
    elif status == "ok":
        outcome = "readings"
    else:
        outcome = status
    return {
        "platform": result.get("platform"),
        "product": result.get("product"),
        "utc_day": utc_day,
        "status": status,
        "coverage": coverage,
        "count": count,
        "outcome": outcome,
        "text": result.get("text") or f"{result.get('platform')}: {outcome}",
    }


def merge_hotspot_payloads(payloads: list[dict], *, observation_date: str) -> dict:
    """Combine multi-UTC-day FIRMS pulls; keep distinct pixels, drop exact duplicates."""

    by_platform: dict[str, dict] = {}
    seen: set[tuple] = set()
    feeds: list[dict] = []
    for payload in payloads:
        utc_day = str(payload.get("date") or "")[:10]
        for result in payload.get("results") or []:
            feeds.append(_feed_row(result, utc_day))
            platform = result.get("platform") or "Unrecognized"
            bucket = by_platform.setdefault(
                platform,
                {
                    "platform": platform,
                    "status": result.get("status") or "ok",
                    "coverage": result.get("coverage") or "unknown",
                    "product": result.get("product"),
                    "processing": result.get("processing"),
                    "hotspots": [],
                    "count": 0,
                    # Track whether every UTC-day piece came from ResponseCache.
                    "_cache_votes": [],
                },
            )
            # Prefer an ok/readings status over failed once any day succeeded.
            if result.get("status") == "ok":
                bucket["status"] = "ok"
            elif result.get("status") == "no_hotspots" and bucket["status"] not in {"ok"}:
                bucket["status"] = "no_hotspots"
            elif bucket["status"] != "ok" and result.get("status"):
                bucket["status"] = result.get("status")
            if result.get("product"):
                bucket["product"] = result.get("product")
            if result.get("processing"):
                bucket["processing"] = result.get("processing")
            if "cached" in result:
                bucket["_cache_votes"].append(bool(result.get("cached")))
            for spot in result.get("hotspots") or []:
                item = dict(spot)
                item.setdefault("platform", platform)
                item.setdefault("source", result.get("product"))
                key = _detection_key(item)
                if key in seen:
                    continue
                seen.add(key)
                bucket["hotspots"].append(item)
            bucket["count"] = len(bucket["hotspots"])

    results = []
    for name in sorted(by_platform):
        row = by_platform[name]
        votes = row.pop("_cache_votes", [])
        # True only when every overlapping UTC day was served from cache.
        row["cached"] = bool(votes) and all(votes)
        if row["status"] == "ok" and row["count"] == 0:
            row["status"] = "no_hotspots"
        results.append(row)
    total = sum(row["count"] for row in results)
    configured = any(payload.get("configured") for payload in payloads) if payloads else False
    return {
        "configured": configured,
        "date": observation_date,
        "total_count": total,
        "combined": {"coverage": "unknown"},
        "results": results,
        "feeds": feeds,
        "utc_days_queried": sorted({str(p.get("date") or "")[:10] for p in payloads if p.get("date")}),
        "dedupe": "Exact platform+UTC time+coordinate repeats removed; distinct pixels and passes kept.",
    }


def filter_payload_to_ph_day(payload: dict, ph_day: str) -> dict:
    """Keep detections whose Asia/Manila local date matches the requested day."""

    results = []
    for result in payload.get("results") or []:
        kept = []
        for spot in result.get("hotspots") or []:
            local = (
                str(spot.get("acq_date_ph") or "")[:10]
                or ph_day_for_utc(str(spot.get("acq_date") or ""), spot.get("acq_time"))
            )
            if local == ph_day:
                item = dict(spot)
                item["acq_date_ph"] = local
                item["ph_date"] = local
                kept.append(item)
        row = dict(result)
        row["hotspots"] = kept
        row["count"] = len(kept)
        results.append(row)
    total = sum(row["count"] for row in results)
    return {**payload, "date": ph_day, "results": results, "total_count": total, "ph_day": ph_day}


def fetch_firms_for_ph_day(
    firms_client,
    ring: list[list[float]],
    ph_day: str,
    platforms: list[str] | None = None,
    *,
    pad: float = 0.05,
) -> dict:
    """Query overlapping UTC dates for one Manila day and clip later via land_check."""

    day = parse_day(ph_day)
    west, south, east, north = polygon_bbox(ring)
    query_box = (west - pad, south - pad, east + pad, north + pad)
    platforms = platforms or list(DEFAULT_PLATFORMS)
    payloads = []
    for utc_day in utc_dates_for_ph_day(day):
        try:
            payloads.append(firms_client.hotspots(*query_box, utc_day, platforms))
        except Exception as exc:  # noqa: BLE001
            payloads.append(
                {
                    "configured": bool(getattr(firms_client, "key", None)),
                    "date": utc_day,
                    "total_count": 0,
                    "combined": {"coverage": "unknown"},
                    "results": [
                        {
                            "platform": platform,
                            "status": "request_failed",
                            "coverage": "unknown",
                            "count": 0,
                            "hotspots": [],
                            "text": f"{platform}: request failed ({exc.__class__.__name__})",
                        }
                        for platform in platforms
                    ],
                }
            )
    merged = merge_hotspot_payloads(payloads, observation_date=day.isoformat())
    return filter_payload_to_ph_day(merged, day.isoformat())


def clip_hotspots_to_ring(payload: dict, ring: list[list[float]]) -> dict:
    """Drop detections outside the drawn polygon (bbox pulls can over-fetch)."""

    heat = classify_detections(payload, ring)
    inside_keys = {
        _detection_key(row)
        for row in (heat.get("inside") or [])
    }
    results = []
    for result in payload.get("results") or []:
        kept = [spot for spot in (result.get("hotspots") or []) if _detection_key(spot) in inside_keys]
        # Also accept points that classify as inside via direct ring test when keys differ slightly.
        if not kept:
            kept = [
                spot
                for spot in (result.get("hotspots") or [])
                if point_in_ring(float(spot.get("lon") or 0), float(spot.get("lat") or 0), ring)
            ]
        row = dict(result)
        row["hotspots"] = kept
        row["count"] = len(kept)
        results.append(row)
    return {
        **payload,
        "results": results,
        "total_count": sum(row["count"] for row in results),
        "clipped_to_polygon": True,
    }
