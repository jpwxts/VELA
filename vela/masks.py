"""Official fire-mask classes for the two Level-2 products Vela compares.

Aqua MODIS MYD14 Collection 6.1 follows Table 3 of the MODIS Collection 6 /
6.1 Active Fire Product User's Guide (Giglio, Schroeder, and Justice).

Suomi-NPP VIIRS VNP14IMG Collection 2 follows Table 1 of the Collection 2
VIIRS 375 m Active Fire Product User's Guide, version 1.2 (Schroeder and
Giglio). The numeric codes are not interchangeable: MODIS class 2 means the
pixel was not processed, while VIIRS class 2 means sun glint.
"""

from __future__ import annotations

import numpy as np

MODIS_CLASSES = {
    0: "missing",
    1: "missing",
    2: "missing",
    3: "water",
    4: "cloud",
    5: "clear",
    6: "unknown",
    7: "fire_low",
    8: "fire_nominal",
    9: "fire_high",
}

VIIRS_CLASSES = {
    0: "missing",
    1: "missing",
    2: "unknown",
    3: "water",
    4: "cloud",
    5: "clear",
    6: "unknown",
    7: "fire_low",
    8: "fire_nominal",
    9: "fire_high",
}

CATEGORIES = (
    "fire_low",
    "fire_nominal",
    "fire_high",
    "clear",
    "cloud",
    "water",
    "unknown",
    "missing",
)

FIRE_CATEGORIES = ("fire_low", "fire_nominal", "fire_high")

CLASS_GUIDE = {
    "modis": {
        "product": "MYD14 Collection 6.1",
        "classes": MODIS_CLASSES,
        "notes": {
            2: "Not processed for another reason. This is missing data, not a clear pixel.",
        },
    },
    "viirs": {
        "product": "VNP14IMG, VJ114IMG, and VJ214IMG Collection 2",
        "classes": VIIRS_CLASSES,
        "notes": {
            1: "Bow-tie deletion. Treated as missing so it cannot become a non-fire label.",
            2: "Sun glint. The pixel was processed, but it is not clear land and not a fire detection.",
        },
    },
}


def class_table(sensor: str) -> dict[int, str]:
    key = sensor.lower()
    if key == "modis":
        return MODIS_CLASSES
    if key == "viirs":
        return VIIRS_CLASSES
    raise ValueError(f"Unknown sensor '{sensor}'. Expected 'modis' or 'viirs'.")


def empty_counts() -> dict[str, int]:
    return {name: 0 for name in CATEGORIES}


def summarize(values, sensor: str) -> dict[str, int]:
    table = class_table(sensor)
    counts = empty_counts()
    array = np.asarray(values, dtype=np.int16).ravel()
    if array.size == 0:
        return counts
    codes, frequencies = np.unique(array, return_counts=True)
    for code, frequency in zip(codes.tolist(), frequencies.tolist()):
        counts[table.get(int(code), "missing")] += int(frequency)
    return counts


def hotspot_count(counts: dict[str, int]) -> int:
    return int(sum(int(counts.get(name, 0)) for name in FIRE_CATEGORIES))


def visible_pixels(counts: dict[str, int]) -> int:
    return hotspot_count(counts) + int(counts.get("clear", 0))


def visible_km2(counts: dict[str, int], pixel_km2: float, cell_area_km2: float) -> float:
    area = visible_pixels(counts) * float(pixel_km2)
    return float(min(float(cell_area_km2), area))


def category_lookup(sensor: str) -> np.ndarray:
    table = class_table(sensor)
    lookup = np.full(16, CATEGORIES.index("missing"), dtype=np.int16)
    for code, name in table.items():
        if 0 <= int(code) < lookup.size:
            lookup[int(code)] = CATEGORIES.index(name)
    return lookup
