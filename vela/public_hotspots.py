"""Shareable public FIRMS hotspot snapshots (no live NASA key required)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from vela.boundaries import geometry_from_preset, load_preset, point_in_geometry, primary_ring_for_display
from vela.hotspot_areas import group_hotspot_areas, public_result_summary
from vela.land_check import build_land_check
from vela.settings import DATA_DIR

PUBLIC_PH_DIR = DATA_DIR / "public" / "philippines"
DEFAULT_DAY = "2026-11-07"


def geojson_path(day: str = DEFAULT_DAY) -> Path:
    return PUBLIC_PH_DIR / f"{day}.geojson"


def load_geojson(day: str = DEFAULT_DAY) -> dict:
    path = geojson_path(day)
    if not path.is_file():
        raise FileNotFoundError(f"Public hotspot snapshot not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def feature_to_hotspot(feature: dict) -> dict:
    props = feature.get("properties") or {}
    lon, lat = feature["geometry"]["coordinates"]
    time_utc = props.get("acq_time_utc") or ""
    raw = str(time_utc).replace(":", "")
    return {
        "lat": float(lat),
        "lon": float(lon),
        "acq_date": props.get("acq_date_utc") or props.get("observation_day_utc"),
        "acq_time": time_utc if ":" in str(time_utc) else (
            f"{raw.zfill(4)[:2]}:{raw.zfill(4)[2:]}" if raw else ""
        ),
        "acq_time_raw": raw,
        "satellite_code": props.get("satellite_code"),
        "platform": props.get("satellite") or "Unrecognized",
        "instrument": props.get("instrument"),
        "confidence": props.get("confidence"),
        "frp": props.get("frp"),
        "brightness": props.get("brightness"),
        "daynight": props.get("daynight"),
        "source": props.get("source") or "NASA FIRMS",
        "place_name": props.get("place_name"),
        "place_or_coordinates": props.get("place_or_coordinates") or props.get("coordinates_text"),
        "coordinates_text": props.get("coordinates_text"),
        "acq_date_ph": props.get("acq_date_ph"),
        "acq_time_ph": props.get("acq_time_ph"),
        "acq_datetime_utc": props.get("acq_datetime_utc"),
        "timezone": props.get("timezone") or "Asia/Manila",
    }


def filter_features(collection: dict, region: str = "philippines") -> list[dict]:
    features = list(collection.get("features") or [])
    if region in {None, "", "philippines", "all", "ph"}:
        return features
    if region != "mindanao":
        raise ValueError(f"Unsupported public hotspot region '{region}'.")
    geometry = geometry_from_preset("mindanao")
    return [
        feature
        for feature in features
        if point_in_geometry(
            float(feature["geometry"]["coordinates"][0]),
            float(feature["geometry"]["coordinates"][1]),
            geometry,
        )
    ]


def hotspot_payload_from_features(features: list[dict], day: str) -> dict:
    by_platform: dict[str, list[dict]] = defaultdict(list)
    for feature in features:
        hotspot = feature_to_hotspot(feature)
        by_platform[hotspot["platform"]].append(hotspot)
    results = []
    for platform, hotspots in sorted(by_platform.items()):
        results.append(
            {
                "platform": platform,
                "status": "ok",
                "coverage": "unknown",
                "count": len(hotspots),
                "product": "public_snapshot",
                "hotspots": hotspots,
            }
        )
    total = sum(row["count"] for row in results)
    payload = {
        "configured": True,
        "date": day,
        "total_count": total,
        "combined": {"coverage": "unknown"},
        "results": results,
        "saved": True,
        "public_snapshot": True,
        "source": "NASA FIRMS public snapshot",
    }
    areas = group_hotspot_areas(payload)
    payload["hotspot_areas"] = areas
    payload["public_result"] = public_result_summary(payload, areas)
    return payload


def empty_forecast(label: str, west: float, south: float, east: float, north: float) -> dict:
    return {
        "ok": True,
        "saved": True,
        "headline": "Saved satellite snapshot · forecast not included",
        "point": {
            "latitude": (south + north) / 2,
            "longitude": (west + east) / 2,
            "label": label,
            "timezone": "Asia/Manila",
        },
        "days": [],
        "fixture": {
            "name": "philippines_public_hotspots",
            "label": "Saved Philippine FIRMS snapshot · not a live network pull",
        },
    }


def _bbox_ring(bbox: dict) -> list[list[float]]:
    west, south, east, north = (
        float(bbox["west"]),
        float(bbox["south"]),
        float(bbox["east"]),
        float(bbox["north"]),
    )
    return [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
    ]


def build_public_land_check(*, day: str = DEFAULT_DAY, region: str = "philippines") -> dict:
    """Build a land-check style payload from the public GeoJSON.

    Features are clipped with the real multipolygon first. The land-check ring is
    the region bbox so pre-filtered island points stay marked inside even when the
    remote classify_detections helper only understands a single ring.
    """

    collection = load_geojson(day)
    features = filter_features(collection, region)
    preset_id = "mindanao" if region == "mindanao" else "philippines"
    preset = load_preset(preset_id)
    geometry = preset["geometry"]
    bbox = preset["bbox"]
    label = preset.get("name") or preset_id
    hotspot_payload = hotspot_payload_from_features(features, day)
    forecast = empty_forecast(
        label,
        float(bbox["west"]),
        float(bbox["south"]),
        float(bbox["east"]),
        float(bbox["north"]),
    )
    # Prefer the largest island outline on the map; classification uses the bbox
    # ring so associated-island detections already kept by filter_features remain inside.
    display_ring = primary_ring_for_display(geometry)
    payload = build_land_check(
        ring=_bbox_ring(bbox),
        forecast=forecast,
        hotspot_payload=hotspot_payload,
        label=label,
        observation_date=day,
        fixture={
            "name": f"philippines_{day}",
            "label": f"Philippines · {day} · NASA FIRMS UTC-day snapshot (includes Philippine dates 7–8 Nov; no map key required)",
            "path": f"data/public/philippines/{day}.geojson",
            "source": "NASA FIRMS",
        },
    )
    payload["heat"]["lead"] += " Saved UTC-day snapshot; Philippine pass dates can fall on the following day. This is not a live NASA search."
    payload["saved"] = True
    payload["public_snapshot"] = True
    payload["region_id"] = preset_id
    payload["region_label"] = label
    payload["geometry"] = geometry
    payload["display_ring"] = display_ring
    payload["counts"] = {
        "detections": hotspot_payload["total_count"],
        "areas": (hotspot_payload.get("hotspot_areas") or {}).get("area_count"),
        "by_satellite": {
            row["platform"]: row["count"] for row in hotspot_payload.get("results") or []
        },
    }
    payload["metadata"] = collection.get("metadata") or {}
    # Keep pre-filtered hotspot_areas authoritative for the public snapshot.
    payload["heat"]["hotspot_areas"] = hotspot_payload.get("hotspot_areas")
    payload["heat"]["public_result"] = hotspot_payload.get("public_result")
    _attach_snapshot_fields(payload["heat"], hotspot_payload)
    return payload


def _attach_snapshot_fields(heat: dict, hotspot_payload: dict) -> None:
    """Copy place/local-time fields from the snapshot into classified rows."""

    by_key = {}
    for result in hotspot_payload.get("results") or []:
        for spot in result.get("hotspots") or []:
            key = (
                round(float(spot["lat"]), 5),
                round(float(spot["lon"]), 5),
                spot.get("acq_date"),
                str(spot.get("acq_time_raw") or spot.get("acq_time") or ""),
                spot.get("platform"),
            )
            by_key[key] = spot

    def enrich(row: dict) -> dict:
        key = (
            round(float(row["lat"]), 5),
            round(float(row["lon"]), 5),
            row.get("acq_date"),
            str(row.get("acq_time_raw") or row.get("acq_time") or "").replace(":", ""),
            row.get("platform"),
        )
        # Also try HH:MM form.
        alt = (
            round(float(row["lat"]), 5),
            round(float(row["lon"]), 5),
            row.get("acq_date"),
            str(row.get("acq_time") or ""),
            row.get("platform"),
        )
        source = by_key.get(key) or by_key.get(alt)
        if not source:
            return row
        for field in (
            "place_name",
            "place_or_coordinates",
            "coordinates_text",
            "acq_date_ph",
            "acq_time_ph",
            "acq_datetime_utc",
            "timezone",
            "confidence",
            "frp",
            "source",
        ):
            if source.get(field) is not None:
                row[field] = source[field]
        return row

    heat["inside"] = [enrich(dict(row)) for row in heat.get("inside") or []]
    heat["nearby"] = [enrich(dict(row)) for row in heat.get("nearby") or []]
    areas = heat.get("hotspot_areas") or {}
    for area in areas.get("areas") or []:
        area["members"] = [enrich(dict(row)) for row in area.get("members") or []]
