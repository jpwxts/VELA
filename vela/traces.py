"""Example cells that can be traced back to the original fire-mask classes."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from vela.geo import local_datetime
from vela.grid import indices, pack
from vela.masks import class_table
from vela.readers import read_pass
from vela.serving import TRACES_PATH
from vela.settings import DATA_DIR, region_by_id, settings

CLASS_LABELS = {
    "modis": {
        0: "not processed, missing",
        1: "not processed, missing",
        2: "not processed for another reason, missing",
        3: "water",
        4: "cloud",
        5: "clear land",
        6: "unknown",
        7: "fire, low confidence",
        8: "fire, nominal confidence",
        9: "fire, high confidence",
    },
    "viirs": {
        0: "missing",
        1: "bow-tie deletion, missing",
        2: "sun glint, not clear land",
        3: "water",
        4: "cloud",
        5: "clear land",
        6: "unclassified, unknown",
        7: "fire, low confidence",
        8: "fire, nominal confidence",
        9: "fire, high confidence",
    },
}


def usable_zero(sensor: str, histogram: dict[int, int]) -> dict:
    """A zero counts only when class 5 clear land is present and fire classes are absent."""

    fire = sum(int(histogram.get(code, 0)) for code in (7, 8, 9))
    clear = int(histogram.get(5, 0))
    product = "Aqua MODIS" if sensor == "modis" else "Suomi-NPP VIIRS"
    usable = fire == 0 and clear > 0
    if usable:
        text = (
            f"{product} classes 7, 8, and 9 contain 0 pixels. "
            f"Class 5, clear land, contains {clear} pixels. "
            "The zero comes from usable land, not from missing data."
        )
    elif fire:
        text = f"{product} has {fire} fire-class pixels, so this side is not a zero."
    else:
        text = (
            f"{product} has no class 5 clear-land pixels, so a zero here would be missing coverage."
        )
    return {
        "usable_land": usable,
        "fire_pixels": fire,
        "clear_land_pixels": clear,
        "text": text,
    }


def _clock(value: str, lon: float) -> dict:
    when = datetime.fromisoformat(str(value))
    if when.tzinfo is None:
        from datetime import timezone

        when = when.replace(tzinfo=timezone.utc)
    local = local_datetime(when, lon)
    return {
        "utc": when.astimezone(when.tzinfo).strftime("%Y-%m-%d %H:%M UTC"),
        "local": local.strftime("%Y-%m-%d %H:%M local"),
    }


def _classes(sensor: str, histogram: dict[int, int]) -> list[dict]:
    labels = CLASS_LABELS[sensor]
    table = class_table(sensor)
    rows = []
    for code in range(10):
        if code not in table and histogram.get(code, 0) == 0:
            continue
        rows.append(
            {
                "code": code,
                "label": labels.get(code, table.get(code, "unlisted")),
                "pixels": int(histogram.get(code, 0)),
            }
        )
    return rows


def _find(name: str) -> Path:
    root = DATA_DIR / "raw"
    direct = [path for path in root.rglob(Path(name).name) if path.is_file()]
    if direct:
        return direct[0]
    matches = [path for path in root.rglob(Path(name).stem + ".*") if path.is_file()]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(f"Could not find {name} under {root}")


def _histograms(read: dict, cell_keys: list[int]) -> dict[int, dict[int, int]]:
    keys = pack(*indices(read["lon"], read["lat"]))
    classes = np.asarray(read["classes"])
    found = {}
    for key in cell_keys:
        selected = keys == int(key)
        codes, counts = np.unique(classes[selected], return_counts=True)
        found[int(key)] = {int(code): int(count) for code, count in zip(codes.tolist(), counts.tolist())}
    return found


def _pick(frame: pd.DataFrame, outcome: str, zero_sensor: str) -> pd.Series:
    part = frame[frame["outcome"] == outcome].copy()
    if "2019-08-20" in set(part["local_date"].astype(str)):
        part = part[part["local_date"].astype(str) == "2019-08-20"]
    clear = part[f"{zero_sensor}_clear"].astype(int)
    fire = (
        part[f"{zero_sensor}_fire_low"].astype(int)
        + part[f"{zero_sensor}_fire_nominal"].astype(int)
        + part[f"{zero_sensor}_fire_high"].astype(int)
    )
    part = part[(fire == 0) & (clear > 0)].sort_values(
        [f"{zero_sensor}_clear", "shared_coverage_fraction"],
        ascending=False,
    )
    if part.empty:
        raise RuntimeError(f"No {outcome} cell has class 5 land and zero fire pixels")
    return part.iloc[0]


def build_examples(table: Path | None = None) -> dict:
    path = table or (DATA_DIR / "processed" / "paired_cells.parquet")
    frame = pd.read_parquet(path)
    nasa = frame[frame["data_origin"] == "nasa"]
    if nasa.empty:
        raise RuntimeError(f"{path} has no NASA rows")
    chosen = {
        "viirs_only": _pick(nasa, "viirs_only", "modis"),
        "modis_only": _pick(nasa, "modis_only", "viirs"),
    }
    sources = {(str(row["modis_file"]), str(row["viirs_file"])) for row in chosen.values()}
    if len(sources) != 1:
        raise RuntimeError("The two example cells come from different passes")
    first = next(iter(chosen.values()))
    region = region_by_id(str(first["region_id"]))
    bbox = (region["west"], region["south"], region["east"], region["north"])
    config = settings()
    modis_read = read_pass(
        _find(str(first["modis_file"])),
        _find(str(first["modis_geo_file"])),
        bbox,
        datetime.fromisoformat(str(first["modis_time"])),
        config,
    )
    viirs_read = read_pass(
        _find(str(first["viirs_file"])),
        _find(str(first["viirs_geo_file"])),
        bbox,
        datetime.fromisoformat(str(first["viirs_time"])),
        config,
    )
    if not modis_read["ok"] or not viirs_read["ok"]:
        raise RuntimeError(f"Could not reread the source masks: {modis_read.get('reason')} {viirs_read.get('reason')}")
    keys = [int(row["cell_key"]) for row in chosen.values()]
    modis_codes = _histograms(modis_read, keys)
    viirs_codes = _histograms(viirs_read, keys)
    del modis_read, viirs_read
    examples = []
    for outcome, row in chosen.items():
        key = int(row["cell_key"])
        zero_sensor = "modis" if outcome == "viirs_only" else "viirs"
        histogram = modis_codes[key] if zero_sensor == "modis" else viirs_codes[key]
        check = usable_zero(zero_sensor, histogram)
        if not check["usable_land"]:
            raise RuntimeError(check["text"])
        from vela.grid import geographic_bounds, unpack

        x_index, y_index = unpack(key)
        west, south, east, north = geographic_bounds(x_index, y_index)
        lon = float(row["center_lon"])
        modis_time = _clock(str(row["modis_time"]), lon)
        viirs_time = _clock(str(row["viirs_time"]), lon)
        examples.append(
            {
                "outcome": outcome,
                "title": "VIIRS only" if outcome == "viirs_only" else "MODIS only",
                "cell_id": row["cell_id"],
                "center_lat": float(row["center_lat"]),
                "center_lon": lon,
                "local_date": str(row["local_date"]),
                "region_id": row["region_id"],
                "bounds": {"west": west, "south": south, "east": east, "north": north},
                "modis_time_utc": modis_time["utc"],
                "modis_time_local": modis_time["local"],
                "viirs_time_utc": viirs_time["utc"],
                "viirs_time_local": viirs_time["local"],
                "shared_coverage_fraction": float(row["shared_coverage_fraction"]),
                "shared_visible_km2": float(row["shared_visible_km2"]),
                "cell_area_km2": float(config["cell_area_km2"]),
                "modis_visible_km2": float(row["modis_visible_km2"]),
                "viirs_visible_km2": float(row["viirs_visible_km2"]),
                "modis_file": row["modis_file"],
                "viirs_file": row["viirs_file"],
                "modis_classes": _classes("modis", modis_codes[key]),
                "viirs_classes": _classes("viirs", viirs_codes[key]),
                "zero_sensor": zero_sensor,
                "zero_check": check,
                "data_origin": row["data_origin"],
            }
        )
    payload = {
        "available": True,
        "source_pass": {
            "modis_file": str(first["modis_file"]),
            "viirs_file": str(first["viirs_file"]),
            "local_date": str(first["local_date"]),
        },
        "examples": examples,
    }
    TRACES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
