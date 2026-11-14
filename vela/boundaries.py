"""Curated island-group geometries for Burn activity presets.

FIRMS still fetches by bounding box. Detections are clipped to these
multipolygons before 5 km grouping so Visayas/Luzon points cannot enter a
Mindanao selection.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from vela.land_check import distance_to_ring_km, normalize_ring, point_in_ring, polygon_bbox
from vela.settings import CONFIG_DIR

BOUNDARIES_DIR = CONFIG_DIR / "boundaries"
PRESET_IDS = ("philippines", "mindanao")


def _load_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def load_preset(preset_id: str) -> dict:
    path = BOUNDARIES_DIR / f"{preset_id}.json"
    if not path.is_file():
        raise KeyError(f"Unknown boundary preset '{preset_id}'.")
    return _load_file(path)


def list_presets() -> list[dict]:
    rows = []
    for preset_id in PRESET_IDS:
        path = BOUNDARIES_DIR / f"{preset_id}.json"
        if not path.is_file():
            continue
        payload = _load_file(path)
        rows.append(
            {
                "id": payload.get("id") or preset_id,
                "name": payload.get("name") or preset_id,
                "label": payload.get("label") or payload.get("name"),
                "bbox": payload.get("bbox"),
                "source": payload.get("source"),
                "attribution": payload.get("attribution"),
            }
        )
    return rows


def geometry_from_preset(preset_id: str) -> dict:
    return load_preset(preset_id)["geometry"]


def rings_from_geometry(geometry: dict) -> list[list[list[float]]]:
    """Return a list of polygons; each polygon is [outer, *holes] as closed rings."""

    if not geometry:
        raise ValueError("Geometry is required.")
    gtype = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if gtype == "Polygon":
        polys = [coordinates]
    elif gtype == "MultiPolygon":
        polys = coordinates
    else:
        raise ValueError(f"Unsupported geometry type: {gtype}")
    out: list[list[list[float]]] = []
    for poly in polys or []:
        if not poly:
            continue
        rings = [normalize_ring(ring) for ring in poly if ring and len(ring) >= 3]
        if rings:
            out.append(rings)
    if not out:
        raise ValueError("Geometry has no usable rings.")
    return out


def geometry_bbox(geometry: dict) -> tuple[float, float, float, float]:
    west = south = east = north = None
    for poly in rings_from_geometry(geometry):
        for ring in poly:
            w, s, e, n = polygon_bbox(ring)
            west = w if west is None else min(west, w)
            south = s if south is None else min(south, s)
            east = e if east is None else max(east, e)
            north = n if north is None else max(north, n)
    return float(west), float(south), float(east), float(north)


def point_in_geometry(lon: float, lat: float, geometry: dict) -> bool:
    for poly in rings_from_geometry(geometry):
        outer, *holes = poly
        if not point_in_ring(lon, lat, outer):
            continue
        if any(point_in_ring(lon, lat, hole) for hole in holes):
            continue
        return True
    return False


def distance_to_geometry_km(lon: float, lat: float, geometry: dict) -> float:
    if point_in_geometry(lon, lat, geometry):
        return 0.0
    best = None
    for poly in rings_from_geometry(geometry):
        for ring in poly:
            distance = distance_to_ring_km(lon, lat, ring)
            best = distance if best is None else min(best, distance)
    return float(best or 0.0)


def geometry_hash(geometry: dict) -> str:
    payload = json.dumps(geometry, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def primary_ring_for_display(geometry: dict) -> list[list[float]]:
    """Largest outer ring — used for map outline when multipolygon drawing is limited."""

    best = None
    best_area = -1.0
    for poly in rings_from_geometry(geometry):
        outer = poly[0]
        west, south, east, north = polygon_bbox(outer)
        area = abs((east - west) * (north - south))
        if area > best_area:
            best_area = area
            best = outer
    if best is None:
        raise ValueError("No display ring available.")
    return best
