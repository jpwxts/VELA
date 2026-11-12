"""VIIRS-only features. The same function is used for training and prediction."""

from __future__ import annotations

import math
from datetime import date, datetime

from vela.masks import CATEGORIES, hotspot_count, visible_km2
from vela.settings import settings

FEATURE_COLUMNS = (
    "viirs_hotspot_pixels",
    "viirs_fire_low",
    "viirs_fire_nominal",
    "viirs_fire_high",
    "viirs_clear_fraction",
    "viirs_cloud_fraction",
    "viirs_water_fraction",
    "viirs_unknown_fraction",
    "viirs_visible_land_km2",
    "center_lat",
    "center_lon",
    "doy_sin",
    "doy_cos",
    "local_hour",
)

# Joint coverage and every MODIS measurement are labels or filters, not inputs.
LEAKED_FEATURE_TOKENS = ("modis_", "shared_", "outcome", "eligible", "exclusion")


def assert_feature_contract() -> None:
    leaked = [name for name in FEATURE_COLUMNS if any(token in name for token in LEAKED_FEATURE_TOKENS)]
    if leaked:
        raise RuntimeError(f"Feature list includes information that is not available from VIIRS: {leaked}")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def viirs_counts_from_mapping(mapping: dict, prefix: str = "viirs") -> dict[str, int]:
    return {name: int(mapping.get(f"{prefix}_{name}", mapping.get(name, 0)) or 0) for name in CATEGORIES}


def feature_values(counts: dict[str, int], lat: float, lon: float, local_day, hour: float, config: dict | None = None) -> dict:
    assert_feature_contract()
    cfg = config or settings()
    observed = sum(int(counts.get(name, 0)) for name in CATEGORIES) - int(counts.get("missing", 0))

    def fraction(name: str) -> float:
        if observed <= 0:
            return 0.0
        return int(counts.get(name, 0)) / observed

    day = _as_date(local_day)
    angle = 2.0 * math.pi * day.timetuple().tm_yday / 365.25
    values = {
        "viirs_hotspot_pixels": float(hotspot_count(counts)),
        "viirs_fire_low": float(counts.get("fire_low", 0)),
        "viirs_fire_nominal": float(counts.get("fire_nominal", 0)),
        "viirs_fire_high": float(counts.get("fire_high", 0)),
        "viirs_clear_fraction": fraction("clear"),
        "viirs_cloud_fraction": fraction("cloud"),
        "viirs_water_fraction": fraction("water"),
        "viirs_unknown_fraction": fraction("unknown"),
        "viirs_visible_land_km2": visible_km2(counts, cfg["viirs_pixel_km2"], cfg["cell_area_km2"]),
        "center_lat": float(lat),
        "center_lon": float(lon),
        "doy_sin": math.sin(angle),
        "doy_cos": math.cos(angle),
        "local_hour": float(hour),
    }
    if tuple(values) != FEATURE_COLUMNS:
        raise RuntimeError("Feature order drifted from FEATURE_COLUMNS.")
    return values


def raw_viirs_active(values: dict) -> float:
    """Approach A: any qualifying VIIRS fire pixel makes the cell-day active."""

    return 1.0 if float(values["viirs_hotspot_pixels"]) >= 1.0 else 0.0
