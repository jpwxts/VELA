"""Nominatim place search and reverse geocoding (OpenStreetMap).

Coverage: worldwide OpenStreetMap address and named-feature data via the public
Nominatim service (https://nominatim.openstreetmap.org). Attribution:
© OpenStreetMap contributors (https://www.openstreetmap.org/copyright).
Usage policy: identify the app with a User-Agent, cache results, and keep to
about one request per second. No API key is required; credentials stay unused.
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Any, Callable

import httpx

from app.db import ResponseCache

USER_AGENT = "VelaFireTimeMachine/0.1 (local NASA Space Apps project; reverse-geocode)"
NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
SOURCE = {
    "name": "OpenStreetMap Nominatim",
    "attribution": "© OpenStreetMap contributors",
    "url": "https://www.openstreetmap.org/copyright",
    "coverage": "Worldwide OpenStreetMap administrative and named-feature data",
    "policy": "https://operations.osmfoundation.org/policies/nominatim/",
}

# Most-specific → broader. Local equivalents worldwide; no single-country terms forced.
SETTLEMENT_KEYS = (
    "neighbourhood",
    "neighborhood",
    "quarter",
    "suburb",
    "city_district",
    "district",
    "borough",
    "hamlet",
    "village",
    "town",
    "city",
    "municipality",
    "city_municipality",
    "locality",
)
ADMIN_KEYS = (
    "county",
    "municipality",  # some countries use this as mid-level only
    "state_district",
    "province",
    "region",
    "state",
    "territory",
    "department",
    "prefecture",
    "oshire",
    "iso3166-2-lvl4",
    "iso3166-2-lvl6",
)
FEATURE_KEYS = (
    "natural",
    "forest",
    "wood",
    "park",
    "nature_reserve",
    "protected_area",
    "national_park",
    "island",
    "islet",
    "archipelago",
    "peninsula",
    "cape",
    "bay",
    "leisure",
    "tourism",
)
COUNTRY_KEYS = ("country",)

_rate_lock = threading.Lock()
_last_request_at = 0.0
_MIN_INTERVAL_SEC = 1.05


def _throttle() -> None:
    global _last_request_at
    with _rate_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _http_get(url: str, params: dict, headers: dict, getter=None) -> Any:
    if getter is not None:
        return getter(url, params, headers)
    _throttle()
    response = httpx.get(url, params=params, headers=headers, timeout=20.0)
    response.raise_for_status()
    return response.json()


def search_places(query: str, getter=None) -> list[dict]:
    text = query.strip()
    if len(text) < 2:
        return []
    params = {"q": text, "format": "jsonv2", "limit": 5}
    headers = {"User-Agent": USER_AGENT}
    payload = _http_get(NOMINATIM_SEARCH, params, headers, getter=getter)
    places = []
    for item in payload:
        south, north, west, east = (float(value) for value in item.get("boundingbox", [])[:4])
        places.append(
            {
                "name": item.get("display_name") or text,
                "west": west,
                "south": south,
                "east": east,
                "north": north,
            }
        )
    return places


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def round_coord(value: float, decimals: int = 3) -> float:
    """~100 m at the equator — enough to share cache entries without over-fetching."""

    return round(float(value), decimals)


def cache_key_for_point(lat: float, lon: float) -> str:
    return f"nominatim:reverse:{round_coord(lat)}:{round_coord(lon)}"


def _unique_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _first_present(address: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = address.get(key)
        if value:
            return str(value).strip()
    return None


def _hierarchy_parts(address: dict) -> tuple[str | None, list[str], str | None]:
    """Return (primary, context_parts, feature_name) from an OSM address dict."""

    feature = _first_present(address, FEATURE_KEYS)
    settlement = None
    for key in SETTLEMENT_KEYS:
        value = address.get(key)
        if not value:
            continue
        # Prefer true settlements over district aliases when both exist.
        if key in {"municipality", "city_municipality"} and settlement:
            continue
        settlement = str(value).strip()
        if key not in {"municipality", "city_municipality", "district", "city_district", "borough"}:
            break

    admin: list[str] = []
    for key in ADMIN_KEYS:
        value = address.get(key)
        if not value:
            continue
        text = str(value).strip()
        if settlement and text.casefold() == settlement.casefold():
            continue
        if feature and text.casefold() == feature.casefold():
            continue
        if text not in admin:
            admin.append(text)

    country = _first_present(address, COUNTRY_KEYS)
    primary = settlement or feature
    context = _unique_parts([*(admin or []), *( [country] if country else [] )])
    if primary:
        context = [part for part in context if part.casefold() != primary.casefold()]
    return primary, context, feature


def _point_in_bbox(lat: float, lon: float, bbox: list | None) -> bool:
    if not bbox or len(bbox) < 4:
        return False
    try:
        south, north, west, east = (float(value) for value in bbox[:4])
    except (TypeError, ValueError):
        return False
    # Nominatim sometimes returns antimeridian-spanning boxes; keep the simple case.
    if west <= east:
        return south <= lat <= north and west <= lon <= east
    return south <= lat <= north and (lon >= west or lon <= east)


def format_place_result(
    payload: dict | None,
    *,
    lat: float,
    lon: float,
    mode: str = "point",
) -> dict:
    """Turn a Nominatim reverse payload into a stable place label for the UI."""

    base = {
        "status": "ok",
        "lat": lat,
        "lon": lon,
        "mode": mode,
        "source": SOURCE,
        "relation": "coordinates",
        "label": None,
        "primary": None,
        "context": None,
        "feature": None,
        "distance_km": None,
        "coordinates_text": f"{lat:.5f}, {lon:.5f}",
    }
    if not payload or payload.get("error"):
        base["status"] = "unavailable"
        base["label"] = base["coordinates_text"]
        return base

    address = payload.get("address") or {}
    primary, context_parts, feature = _hierarchy_parts(address)
    result_lat = float(payload.get("lat") or lat)
    result_lon = float(payload.get("lon") or lon)
    distance = haversine_km(lat, lon, result_lat, result_lon)
    bbox = payload.get("boundingbox")
    inside_bbox = _point_in_bbox(lat, lon, bbox)
    osm_class = (payload.get("class") or "").lower()
    osm_type = (payload.get("type") or "").lower()
    named = (payload.get("name") or "").strip() or primary

    # Named natural / park / island features containing the point.
    feature_classes = {"natural", "leisure", "boundary", "landuse", "waterway", "place"}
    is_named_feature = bool(feature) or (
        named
        and osm_class in feature_classes
        and osm_type in {
            "forest",
            "wood",
            "park",
            "nature_reserve",
            "protected_area",
            "national_park",
            "island",
            "islet",
            "archipelago",
            "peninsula",
            "bay",
            "cape",
            "national_park",
            "conservation",
        }
    )

    if is_named_feature and (inside_bbox or distance < 2.0 or feature):
        feature_name = feature or named
        context = ", ".join(context_parts) if context_parts else None
        label_parts = _unique_parts([feature_name, *(context_parts or [])])
        base.update(
            {
                "relation": "inside",
                "primary": feature_name,
                "feature": feature_name,
                "context": context,
                "label": ", ".join(label_parts),
                "distance_km": round(distance, 1) if distance >= 0.1 else 0.0,
            }
        )
        return base

    # Distant named settlement/landmark without admin containment → "Near …".
    settlement_types = {
        "village",
        "town",
        "city",
        "hamlet",
        "municipality",
        "suburb",
        "neighbourhood",
        "neighborhood",
        "locality",
        "isolated_dwelling",
    }
    if named and osm_type in settlement_types and not inside_bbox and distance >= 3.0:
        context = ", ".join(context_parts) if context_parts else None
        approx = _format_distance(distance)
        display = f"Near {named} · approximately {approx} away"
        if context:
            display = f"{display} · {context}"
        if mode == "center":
            display = f"Area near {named} · approximately {approx} away"
            if context:
                display = f"{display} · {context}"
            relation = "area_near"
        else:
            relation = "near"
        base.update(
            {
                "relation": relation,
                "primary": named,
                "feature": feature,
                "context": context,
                "label": display,
                "distance_km": round(distance, 1),
            }
        )
        return base

    if primary:
        context = ", ".join(context_parts) if context_parts else None
        label = ", ".join(_unique_parts([primary, *(context_parts or [])]))
        # Settlements returned far from the query are "near", not containment.
        settlement_far = distance >= 3.0 and not inside_bbox and not address.get("city") and not address.get(
            "town"
        ) and not address.get("village") and not address.get("hamlet") and not address.get("municipality")
        # If address includes a settlement key, Nominatim treats the point as inside that unit.
        has_settlement = any(address.get(key) for key in SETTLEMENT_KEYS)
        if has_settlement and (inside_bbox or distance < 25.0):
            relation = "inside"
            display = label
        elif settlement_far or (named and distance >= 3.0 and not has_settlement):
            relation = "near"
            approx = _format_distance(distance)
            display = f"Near {named or primary} · approximately {approx} away"
            if context:
                display = f"{display} · {context}"
        else:
            relation = "inside"
            display = label
        if mode == "center" and relation == "inside":
            relation = "area_near"
            display = f"Area near {label}"
        elif mode == "center" and relation == "near":
            relation = "area_near"
            display = f"Area near {named or primary} · approximately {_format_distance(distance)} away"
            if context:
                display = f"{display} · {context}"
        base.update(
            {
                "relation": relation,
                "primary": primary,
                "feature": feature,
                "context": context,
                "label": display,
                "distance_km": round(distance, 1),
            }
        )
        return base

    # Admin-only (state/province/country) without a local settlement name.
    if context_parts:
        label = ", ".join(context_parts)
        if mode == "center":
            base.update(
                {
                    "relation": "area_near",
                    "primary": context_parts[0],
                    "context": ", ".join(context_parts[1:]) if len(context_parts) > 1 else None,
                    "label": f"Area near {label}",
                    "distance_km": round(distance, 1),
                }
            )
        else:
            base.update(
                {
                    "relation": "inside",
                    "primary": context_parts[0],
                    "context": ", ".join(context_parts[1:]) if len(context_parts) > 1 else None,
                    "label": label,
                    "distance_km": round(distance, 1),
                }
            )
        return base

    base["status"] = "unavailable"
    base["label"] = base["coordinates_text"]
    return base


def _format_distance(km: float) -> str:
    if km < 1:
        return f"{max(100, int(round(km * 1000)))} m"
    if km < 10:
        return f"{km:.1f} km"
    return f"{int(round(km))} km"


def reverse_lookup(
    lat: float,
    lon: float,
    *,
    cache: ResponseCache | None = None,
    getter=None,
    max_age_hours: float = 24 * 30,
) -> dict | None:
    """Fetch Nominatim reverse JSON for a point, using the SQLite cache when available."""

    key = cache_key_for_point(lat, lon)
    if cache is not None:
        cached = cache.get(key, max_age_hours=max_age_hours)
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                pass

    params = {
        "lat": f"{float(lat):.7f}",
        "lon": f"{float(lon):.7f}",
        "format": "jsonv2",
        "addressdetails": 1,
        "zoom": 18,
        "namedetails": 0,
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        payload = _http_get(NOMINATIM_REVERSE, params, headers, getter=getter)
    except Exception:  # noqa: BLE001
        return None
    if cache is not None and payload is not None:
        cache.put(key, "nominatim_reverse", json.dumps(payload))
    return payload


def identify_point(
    lat: float,
    lon: float,
    *,
    mode: str = "point",
    cache: ResponseCache | None = None,
    getter=None,
) -> dict:
    payload = reverse_lookup(lat, lon, cache=cache, getter=getter)
    return format_place_result(payload, lat=lat, lon=lon, mode=mode)


def identify_members(
    members: list[dict],
    *,
    center_lat: float | None = None,
    center_lon: float | None = None,
    cache: ResponseCache | None = None,
    getter=None,
    max_lookups: int = 4,
) -> dict:
    """Identify places for detection members in a 5 km square.

    Uses member coordinates when present. If members span multiple named places,
    the label says so. Falls back to the square center as “Area near …”.
    """

    points: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for member in members or []:
        try:
            lat = float(member["lat"])
            lon = float(member["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        key = (round_coord(lat), round_coord(lon))
        if key in seen:
            continue
        seen.add(key)
        points.append((lat, lon))
        if len(points) >= max_lookups:
            break

    results: list[dict] = []
    for lat, lon in points:
        results.append(identify_point(lat, lon, mode="point", cache=cache, getter=getter))

    usable = [row for row in results if row.get("primary") and row.get("relation") != "coordinates"]
    if not usable:
        if center_lat is not None and center_lon is not None:
            return identify_point(center_lat, center_lon, mode="center", cache=cache, getter=getter)
        return {
            "status": "unavailable",
            "relation": "coordinates",
            "label": None,
            "primary": None,
            "context": None,
            "source": SOURCE,
            "places": results,
            "mode": "members",
        }

    # Group by primary name (case-insensitive).
    groups: dict[str, dict] = {}
    for row in usable:
        key = str(row["primary"]).casefold()
        groups.setdefault(key, row)

    if len(groups) == 1:
        only = next(iter(groups.values()))
        # Member lookups are reliable containment/near for the readings themselves.
        return {
            **only,
            "mode": "members",
            "places": results,
            "status": "ok",
        }

    names = _unique_parts([row["primary"] for row in groups.values()])
    contexts = _unique_parts([row.get("context") or "" for row in groups.values() if row.get("context")])
    shared_context = contexts[0] if len(contexts) == 1 else None
    if len(names) == 2:
        span = f"Readings span {names[0]} and {names[1]}"
    else:
        span = f"Readings span {', '.join(names[:-1])}, and {names[-1]}"
    if shared_context:
        span = f"{span} · {shared_context}"
    return {
        "status": "ok",
        "relation": "inside",
        "label": span,
        "primary": names[0],
        "context": shared_context,
        "feature": None,
        "distance_km": None,
        "source": SOURCE,
        "places": results,
        "mode": "members",
        "multiple": True,
        "names": names,
    }


def identify_selection(
    *,
    mode: str,
    lat: float | None = None,
    lon: float | None = None,
    members: list[dict] | None = None,
    center_lat: float | None = None,
    center_lon: float | None = None,
    cache: ResponseCache | None = None,
    getter: Callable | None = None,
) -> dict:
    if mode == "members":
        return identify_members(
            members or [],
            center_lat=center_lat if center_lat is not None else lat,
            center_lon=center_lon if center_lon is not None else lon,
            cache=cache,
            getter=getter,
        )
    if lat is None or lon is None:
        return {
            "status": "unavailable",
            "relation": "coordinates",
            "label": None,
            "source": SOURCE,
            "mode": mode,
        }
    return identify_point(lat, lon, mode=mode if mode in {"point", "center"} else "point", cache=cache, getter=getter)
