"""Shared-coverage rule for one 5 km cell on one local date."""

from __future__ import annotations

from vela.masks import empty_counts, hotspot_count, visible_km2
from vela.settings import settings

COVERAGE_RULE = (
    "A cell-day is usable only when land visible to both Aqua MODIS and "
    "Suomi-NPP VIIRS covers at least half of the 25 km² cell. Visible land "
    "is clear land or a detected fire. Cloud, water, unknown, sun glint, "
    "bow-tie deletion, and unprocessed pixels do not count. Shared area is "
    "the smaller of the two sensors' visible-land areas, using nominal pixel "
    "areas of 1 km² for MODIS and 0.140625 km² for VIIRS. If either sensor "
    "has no processed pixels in the cell, the cell-day is missing and is not "
    "labeled as a day without fire."
)


def _complete(counts: dict | None) -> dict[str, int]:
    base = empty_counts()
    if counts:
        for key, value in counts.items():
            if key in base:
                base[key] = int(value)
    return base


def _unprocessed(counts: dict[str, int]) -> bool:
    total = sum(counts.values())
    return total == 0 or counts["missing"] == total


def classify_cell(
    modis_counts: dict | None,
    viirs_counts: dict | None,
    config: dict | None = None,
) -> dict:
    """Decide whether one cell-day can support a MODIS label.

    Eligible rows keep one of four outcomes: both, viirs_only, modis_only,
    or neither. A missing or poorly observed cell does not enter the neither
    class.
    """

    cfg = config or settings()
    modis = _complete(modis_counts)
    viirs = _complete(viirs_counts)
    cell_area = float(cfg["cell_area_km2"])
    minimum = float(cfg["min_shared_coverage"])
    modis_area = visible_km2(modis, cfg["modis_pixel_km2"], cell_area)
    viirs_area = visible_km2(viirs, cfg["viirs_pixel_km2"], cell_area)
    shared = min(modis_area, viirs_area)
    fraction = shared / cell_area if cell_area else 0.0
    modis_hot = hotspot_count(modis)
    viirs_hot = hotspot_count(viirs)

    reason = None
    if _unprocessed(modis):
        reason = "missing_modis"
    elif _unprocessed(viirs):
        reason = "missing_viirs"
    elif fraction + 1e-12 < minimum:
        reason = "insufficient_shared_land"

    eligible = reason is None
    if not eligible:
        outcome = None
        modis_detected = None
        viirs_active = None
    else:
        modis_detected = modis_hot > 0
        viirs_active = viirs_hot > 0
        if modis_detected and viirs_active:
            outcome = "both"
        elif viirs_active:
            outcome = "viirs_only"
        elif modis_detected:
            outcome = "modis_only"
        else:
            outcome = "neither"

    return {
        "eligible": eligible,
        "exclusion_reason": reason,
        "outcome": outcome,
        "modis_detected": modis_detected,
        "viirs_active": viirs_active,
        "modis_hotspot_pixel_count": modis_hot,
        "viirs_hotspot_pixel_count": viirs_hot,
        "modis_visible_km2": modis_area,
        "viirs_visible_km2": viirs_area,
        "shared_visible_km2": shared,
        "shared_coverage_fraction": fraction,
        "modis_counts": modis,
        "viirs_counts": viirs,
    }
