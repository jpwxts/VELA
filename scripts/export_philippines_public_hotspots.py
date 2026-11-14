#!/usr/bin/env python3
"""Export verified Philippine FIRMS detections to a shareable GeoJSON snapshot.

Reads deduplicated rows from data/cache/firms.sqlite for one UTC day, clips them
to config/boundaries/philippines.json, and writes:

  data/public/philippines/YYYY-MM-DD.geojson

No FIRMS map key is required at export time when the day is already cached.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.firms import parse_hotspots
from vela.boundaries import geometry_from_preset, point_in_geometry
from vela.settings import DATA_DIR, ROOT

MANILA = ZoneInfo("Asia/Manila")


def _dedupe_key(hotspot: dict) -> tuple:
    return (
        round(float(hotspot["lat"]), 5),
        round(float(hotspot["lon"]), 5),
        hotspot.get("acq_date"),
        hotspot.get("acq_time_raw") or hotspot.get("acq_time"),
        hotspot.get("satellite_code") or hotspot.get("platform"),
        hotspot.get("instrument"),
        hotspot.get("frp"),
        hotspot.get("confidence"),
    )


def _load_cached_day(day: str) -> tuple[list[dict], int]:
    cache = DATA_DIR / "cache" / "firms.sqlite"
    if not cache.is_file():
        raise FileNotFoundError(f"FIRMS cache not found at {cache}")
    con = sqlite3.connect(cache)
    payloads = [
        row[0]
        for row in con.execute(
            "SELECT payload FROM response_cache "
            "WHERE payload LIKE 'latitude,longitude%' AND payload LIKE ?",
            (f"%{day}%",),
        )
    ]
    seen: dict[tuple, dict] = {}
    raw = 0
    for text in payloads:
        rows = [item for item in parse_hotspots(text) if item.get("acq_date") == day]
        raw += len(rows)
        for item in rows:
            seen[_dedupe_key(item)] = item
    return list(seen.values()), raw


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _load_place_index() -> list[tuple[float, float, str]]:
    path = DATA_DIR / "cache" / "places.sqlite"
    if not path.is_file():
        return []
    places: list[tuple[float, float, str]] = []
    con = sqlite3.connect(path)
    for (payload,) in con.execute("SELECT payload FROM response_cache"):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        try:
            lat = float(data.get("lat"))
            lon = float(data.get("lon"))
        except (TypeError, ValueError):
            continue
        address = data.get("address") or {}
        country = str(address.get("country_code") or "").lower()
        display = data.get("display_name") or ""
        if country != "ph" and "Philippines" not in display:
            continue
        village = (
            address.get("suburb")
            or address.get("village")
            or address.get("neighbourhood")
            or address.get("hamlet")
        )
        city = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("city_district")
        )
        province = address.get("state") or address.get("region") or address.get("province")
        if village and city:
            label = f"{village}, {city}"
        elif city and province:
            label = f"{city}, {province}"
        elif village and province:
            label = f"{village}, {province}"
        else:
            parts = [part.strip() for part in display.split(",") if part.strip() and part.strip() != "Philippines"]
            label = ", ".join(parts[:2]) if parts else ""
        if label:
            places.append((lat, lon, label))
    return places


def _nearest_place(lat: float, lon: float, places: list[tuple[float, float, str]], max_km: float = 5.0) -> str | None:
    best = None
    best_distance = None
    for place_lat, place_lon, label in places:
        distance = _haversine_km(lat, lon, place_lat, place_lon)
        if distance <= max_km and (best_distance is None or distance < best_distance):
            best = label
            best_distance = distance
    return best


def _ph_local(acq_date: str, acq_time: str | None) -> tuple[str | None, str | None]:
    text = str(acq_time or "").strip()
    if len(text) <= 4 and text.isdigit():
        text = text.zfill(4)
        hour, minute = int(text[:2]), int(text[2:])
    elif ":" in text:
        hour_text, minute_text = text.split(":", 1)
        hour, minute = int(hour_text), int(minute_text[:2])
    else:
        return None, None
    utc = datetime(
        int(acq_date[:4]),
        int(acq_date[5:7]),
        int(acq_date[8:10]),
        hour,
        minute,
        tzinfo=timezone.utc,
    )
    local = utc.astimezone(MANILA)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def _datetime_utc(acq_date: str, acq_time: str | None, acq_time_raw: str | None) -> str:
    if acq_time and ":" in str(acq_time):
        return f"{acq_date}T{acq_time}:00Z"
    raw = str(acq_time_raw or acq_time or "0000").strip()
    if raw.isdigit():
        raw = raw.zfill(4)
        return f"{acq_date}T{raw[:2]}:{raw[2:]}:00Z"
    return f"{acq_date}T00:00:00Z"


def export_day(day: str) -> Path:
    unique, raw_count = _load_cached_day(day)
    philippines = geometry_from_preset("philippines")
    mindanao = geometry_from_preset("mindanao")
    inside = [row for row in unique if point_in_geometry(row["lon"], row["lat"], philippines)]
    mindanao_rows = [row for row in inside if point_in_geometry(row["lon"], row["lat"], mindanao)]
    places = _load_place_index()

    features = []
    for row in sorted(
        inside,
        key=lambda item: (
            item.get("acq_time") or item.get("acq_time_raw") or "",
            item["lat"],
            item["lon"],
            item["platform"],
        ),
    ):
        # Prefer formatted HH:MM; fall back to zero-padded raw FIRMS time.
        local_date, local_time = _ph_local(row["acq_date"], row.get("acq_time") or row.get("acq_time_raw"))
        place = _nearest_place(row["lat"], row["lon"], places)
        coords_text = f"{row['lat']:.5f}, {row['lon']:.5f}"
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
                "properties": {
                    "satellite": row["platform"],
                    "satellite_code": row.get("satellite_code"),
                    "instrument": row.get("instrument"),
                    "acq_date_utc": row["acq_date"],
                    "acq_time_utc": row.get("acq_time") or row.get("acq_time_raw"),
                    "acq_datetime_utc": _datetime_utc(
                        row["acq_date"], row.get("acq_time"), row.get("acq_time_raw")
                    ),
                    "acq_date_ph": local_date,
                    "acq_time_ph": local_time,
                    "timezone": "Asia/Manila",
                    "confidence": row.get("confidence"),
                    "frp": row.get("frp"),
                    "brightness": row.get("brightness"),
                    "daynight": row.get("daynight"),
                    "place_name": place,
                    "place_or_coordinates": place or coords_text,
                    "coordinates_text": coords_text,
                    "source": "NASA FIRMS",
                    "observation_day_utc": day,
                },
            }
        )

    without_terra = [feature for feature in features if feature["properties"]["satellite"] != "Terra"]
    mindanao_without_terra = [row for row in mindanao_rows if row["platform"] != "Terra"]
    out = DATA_DIR / "public" / "philippines" / f"{day}.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "title": "Philippine NASA FIRMS satellite heat detections",
            "observation_day_utc": day,
            "boundary": "Philippines island-group geometry (config/boundaries/philippines.json)",
            "source": "NASA FIRMS",
            "source_record_count_raw_cache_rows": raw_count,
            "source_record_count_unique": len(unique),
            "exported_philippines_count": len(features),
            "mindanao_count_same_file_filtered": len(mindanao_rows),
            "counts_by_satellite": dict(Counter(feature["properties"]["satellite"] for feature in features)),
            "mindanao_counts_by_satellite": dict(Counter(row["platform"] for row in mindanao_rows)),
            "comparison_note": (
                "Earlier live Burn-activity UI (Terra unchecked) reported 45 detections and 39 grouped areas. "
                f"This export has {len(features)} Philippine detections including Terra "
                f"({len(features) - len(without_terra)}); without Terra the count is {len(without_terra)}. "
                f"Mindanao filter of this file: {len(mindanao_rows)} detections "
                f"({len(mindanao_without_terra)} without Terra)."
            ),
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", default="2026-11-07")
    args = parser.parse_args()
    path = export_day(args.day)
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data["metadata"]
    print(f"wrote {path.relative_to(ROOT)}")
    print(f"unique source records: {meta['source_record_count_unique']}")
    print(f"Philippines exported: {meta['exported_philippines_count']}")
    print(f"Mindanao filtered: {meta['mindanao_count_same_file_filtered']}")
    print(f"by satellite: {meta['counts_by_satellite']}")


if __name__ == "__main__":
    main()
