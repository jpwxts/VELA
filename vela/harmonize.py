"""Build paired 5 km cell-days from cropped swaths."""

from __future__ import annotations

from collections import Counter

import numpy as np

from vela.coverage import classify_cell
from vela.geo import local_date, local_hour
from vela.grid import cell_identifier, center, indices, pack, unpack
from vela.masks import CATEGORIES, category_lookup
from vela.settings import settings

COUNT_FIELDS = tuple(f"{sensor}_{name}" for sensor in ("modis", "viirs") for name in CATEGORIES)


def aggregate(lon, lat, classes, sensor: str) -> dict[int, dict[str, int]]:
    lon = np.asarray(lon)
    lat = np.asarray(lat)
    classes = np.asarray(classes, dtype=np.int16).ravel()
    if classes.size == 0:
        return {}
    x_index, y_index = indices(lon, lat)
    keys = pack(x_index, y_index)
    lookup = category_lookup(sensor)
    mapped = lookup[np.clip(classes, 0, lookup.size - 1)]
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    table = np.zeros((unique_keys.size, len(CATEGORIES)), dtype=np.int32)
    np.add.at(table, (inverse, mapped), 1)
    grouped = {}
    for row_index, key in enumerate(unique_keys.tolist()):
        grouped[int(key)] = {
            name: int(table[row_index, column]) for column, name in enumerate(CATEGORIES)
        }
    return grouped


def _flatten_counts(prefix: str, counts: dict[str, int]) -> dict[str, int]:
    return {f"{prefix}_{name}": int(counts.get(name, 0)) for name in CATEGORIES}


def rows_for_pair(modis_cells: dict, viirs_cells: dict, meta: dict, config: dict | None = None) -> list[dict]:
    cfg = config or settings()
    target_hour = float(cfg["aqua_local_hour"])
    rows = []
    for key in set(modis_cells) | set(viirs_cells):
        modis_counts = modis_cells.get(key)
        viirs_counts = viirs_cells.get(key)
        x_index, y_index = unpack(key)
        longitude, latitude = center(x_index, y_index)
        decision = classify_cell(modis_counts, viirs_counts, cfg)
        modis_day = local_date(meta["modis_time"], longitude)
        viirs_day = local_date(meta["viirs_time"], longitude)
        viirs_hour = local_hour(meta["viirs_time"], longitude)
        modis_hour = local_hour(meta["modis_time"], longitude)
        if decision["eligible"] and modis_day != viirs_day:
            decision = {
                **decision,
                "eligible": False,
                "exclusion_reason": "local_date_mismatch",
                "outcome": None,
                "modis_detected": None,
                "viirs_active": None,
            }
        shared_day = modis_day if modis_day == viirs_day else modis_day
        origin = "nasa"
        file_names = f"{meta['modis_file']} {meta['viirs_file']}".lower()
        if "synthetic" in file_names:
            origin = "synthetic"
        row = {
            "cell_id": cell_identifier(x_index, y_index),
            "cell_key": int(key),
            "center_lon": longitude,
            "center_lat": latitude,
            "local_date": shared_day.isoformat(),
            "local_hour": viirs_hour,
            "modis_local_hour": modis_hour,
            "hours_from_aqua": abs(modis_hour - target_hour),
            "region_id": meta["region_id"],
            "region_name": meta.get("region_name", meta["region_id"]),
            "landscape": meta.get("landscape", ""),
            "role": meta.get("role", "unspecified"),
            "modis_file": meta["modis_file"],
            "viirs_file": meta["viirs_file"],
            "viirs_platform": meta.get("viirs_platform") or "Suomi-NPP",
            "modis_geo_file": meta["modis_geo_file"],
            "viirs_geo_file": meta["viirs_geo_file"],
            "modis_time": meta["modis_time"].isoformat(),
            "viirs_time": meta["viirs_time"].isoformat(),
            "modis_detected": decision["modis_detected"],
            "viirs_hotspot_pixel_count": decision["viirs_hotspot_pixel_count"],
            "modis_hotspot_pixel_count": decision["modis_hotspot_pixel_count"],
            "shared_visible_km2": decision["shared_visible_km2"],
            "shared_coverage_fraction": decision["shared_coverage_fraction"],
            "modis_visible_km2": decision["modis_visible_km2"],
            "viirs_visible_km2": decision["viirs_visible_km2"],
            "outcome": decision["outcome"],
            "eligible": bool(decision["eligible"]),
            "exclusion_reason": decision["exclusion_reason"],
            "data_origin": origin,
        }
        row.update(_flatten_counts("modis", decision["modis_counts"]))
        row.update(_flatten_counts("viirs", decision["viirs_counts"]))
        rows.append(row)
    return rows


def choose_one(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep one daytime pair per cell, local date, and VIIRS platform.

    Prefer a pair that meets the coverage rule. Break remaining ties by
    shared visible land, then by closeness to the 13:30 Aqua overpass.
    NOAA-20 and NOAA-21 stay in their own groups. The calendar, not this
    step, chooses the single contribution across platforms.
    """

    grouped: dict[tuple, list] = {}
    for row in rows:
        platform = row.get("viirs_platform") or "Suomi-NPP"
        grouped.setdefault((row["cell_id"], row["local_date"], platform), []).append(row)
    kept = []
    duplicates = []
    for group in grouped.values():
        group.sort(
            key=lambda row: (
                1 if row["eligible"] else 0,
                float(row["shared_visible_km2"]),
                -float(row["hours_from_aqua"]),
            ),
            reverse=True,
        )
        kept.append(group[0])
        for other in group[1:]:
            duplicate = dict(other)
            duplicate["eligible"] = False
            duplicate["outcome"] = None
            duplicate["modis_detected"] = None
            duplicate["exclusion_reason"] = "duplicate_pass_not_selected"
            duplicates.append(duplicate)
    return kept, duplicates


def split_kept(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    eligible = [row for row in rows if row["eligible"]]
    excluded = [row for row in rows if not row["eligible"]]
    return eligible, excluded


def exclusion_summary(rows: list[dict]) -> dict[str, int]:
    return dict(Counter(row.get("exclusion_reason") or "unspecified" for row in rows))
