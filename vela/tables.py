"""Read and write the compact paired-cell tables."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from vela.coverage import COVERAGE_RULE
from vela.harmonize import choose_one, split_kept
from vela.settings import DATA_DIR

PAIRED_NAME = "paired_cells.parquet"
EXCLUDED_NAME = "excluded_cells.parquet"


def pass_shard_name(region_id: str, modis_file: str) -> str:
    """One shard per Aqua pass, so a rerun replaces that pass instead of appending it."""

    match = re.search(r"A(\d{7})\.(\d{4})", str(modis_file))
    if not match:
        raise ValueError(f"Cannot name a shard from '{modis_file}'")
    return f"{region_id}_{match.group(1)}_{match.group(2)}.parquet"


def write_pass_shard(rows: list[dict], region_id: str, modis_file: str) -> Path:
    folder = DATA_DIR / "processed" / "shards"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / pass_shard_name(region_id, modis_file)
    write_rows(rows, target)
    stem = Path(str(modis_file)).stem
    for path in folder.glob("*.parquet"):
        if path == target:
            continue
        try:
            names = pd.read_parquet(path, columns=["modis_file"])["modis_file"].dropna().astype(str).unique()
        except (KeyError, OSError, ValueError):
            continue
        if len(names) == 1 and Path(names[0]).stem == stem:
            path.unlink()
    return target


def write_rows(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if "modis_detected" in frame.columns:
        frame["modis_detected"] = frame["modis_detected"].astype("boolean")
    if "eligible" in frame.columns:
        frame["eligible"] = frame["eligible"].astype(bool)
    frame.to_parquet(path, index=False)
    return path


def shard_paths() -> list[Path]:
    folder = DATA_DIR / "processed" / "shards"
    if not folder.exists():
        return []
    return sorted(folder.glob("*.parquet"))


def compact_shards() -> dict:
    frames = [pd.read_parquet(path) for path in shard_paths()]
    if not frames:
        return {"eligible": 0, "excluded": 0, "shards": 0}
    rows = pd.concat(frames, ignore_index=True).to_dict("records")
    kept, duplicates = choose_one(rows)
    eligible, excluded = split_kept(kept)
    excluded.extend(duplicates)
    processed = DATA_DIR / "processed"
    write_rows(eligible, processed / PAIRED_NAME)
    write_rows(excluded, processed / EXCLUDED_NAME)
    summary = {
        "shards": len(frames),
        "eligible": len(eligible),
        "excluded": len(excluded),
        "paired_cells": str(processed / PAIRED_NAME),
        "excluded_cells": str(processed / EXCLUDED_NAME),
    }
    (processed / "table_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def write_trace(row: dict | None, extra: dict | None = None) -> Path | None:
    if row is None:
        return None
    from vela.grid import geographic_bounds, unpack

    from vela.masks import CATEGORIES

    x_index, y_index = unpack(int(row["cell_key"]))
    west, south, east, north = geographic_bounds(x_index, y_index)
    payload = {
        "cell_id": row["cell_id"],
        "center_lat": row["center_lat"],
        "center_lon": row["center_lon"],
        "local_date": row["local_date"],
        "outcome": row.get("outcome"),
        "exclusion_reason": row.get("exclusion_reason"),
        "modis_detected": row.get("modis_detected"),
        "viirs_hotspot_pixel_count": row.get("viirs_hotspot_pixel_count"),
        "shared_coverage_fraction": row.get("shared_coverage_fraction"),
        "modis_file": row.get("modis_file"),
        "viirs_file": row.get("viirs_file"),
        "modis_time": row.get("modis_time"),
        "viirs_time": row.get("viirs_time"),
        "bounds": {"west": west, "south": south, "east": east, "north": north},
        "counts": {
            "modis": {name: row.get(f"modis_{name}", 0) for name in CATEGORIES},
            "viirs": {name: row.get(f"viirs_{name}", 0) for name in CATEGORIES},
        },
        "rule": COVERAGE_RULE,
        "data_origin": row.get("data_origin"),
    }
    if extra:
        payload["pass"] = extra
    path = DATA_DIR / "processed" / "cell_trace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def choose_trace_row(eligible: list[dict], excluded: list[dict]) -> dict | None:
    order = {"both": 0, "neither": 1, "viirs_only": 2, "modis_only": 3}
    if eligible:
        return sorted(eligible, key=lambda row: order.get(row.get("outcome"), 9))[0]
    return excluded[0] if excluded else None
