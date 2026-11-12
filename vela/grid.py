"""Fixed 5 km equal-area grid on the WGS 84 NSIDC EASE-Grid 2.0 projection."""

from __future__ import annotations

import numpy as np
from pyproj import Transformer

from vela.settings import settings

TO_EASE = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
FROM_EASE = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)


def cell_size_m() -> float:
    return float(settings()["grid_m"])


def indices(lon, lat) -> tuple[np.ndarray, np.ndarray]:
    x_coord, y_coord = TO_EASE.transform(lon, lat)
    size = cell_size_m()
    x_index = np.floor(np.asarray(x_coord, dtype=np.float64) / size).astype(np.int64)
    y_index = np.floor(np.asarray(y_coord, dtype=np.float64) / size).astype(np.int64)
    return x_index, y_index


def pack(x_index, y_index) -> np.ndarray:
    return (np.asarray(x_index, dtype=np.int64) + 100_000) * 1_000_000 + (
        np.asarray(y_index, dtype=np.int64) + 100_000
    )


def unpack(key: int) -> tuple[int, int]:
    x_index = int(key) // 1_000_000 - 100_000
    y_index = int(key) % 1_000_000 - 100_000
    return x_index, y_index


def center(x_index: int, y_index: int) -> tuple[float, float]:
    size = cell_size_m()
    longitude, latitude = FROM_EASE.transform((x_index + 0.5) * size, (y_index + 0.5) * size)
    return float(longitude), float(latitude)


def cell_identifier(x_index: int, y_index: int) -> str:
    return f"{int(x_index)}:{int(y_index)}"


def geographic_bounds(x_index: int, y_index: int) -> tuple[float, float, float, float]:
    size = cell_size_m()
    corners = [
        FROM_EASE.transform((x_index + dx) * size, (y_index + dy) * size)
        for dx in (0, 1)
        for dy in (0, 1)
    ]
    longitudes = [float(item[0]) for item in corners]
    latitudes = [float(item[1]) for item in corners]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)
