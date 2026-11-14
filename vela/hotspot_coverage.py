"""Single-platform fire-mask coverage for Mindanao hotspot-forecast labels.

Distinct from Aqua–Suomi joint harmonization coverage. A daytime no-detection
pass with enough visible land supports a statement about that observation time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from vela.firms_day import ph_day_for_utc
from vela.geo import local_date, local_hour
from vela.grid import cell_identifier, center, indices, pack, unpack
from vela.harmonize import aggregate
from vela.hotspot_forecast import STUDY
from vela.masks import hotspot_count, visible_km2
from vela.pairing import complete_passes, index_passes
from vela.readers import read_pass
from vela.settings import DATA_DIR, settings

COVERAGE_PATH = DATA_DIR / "processed" / "philippines_hotspot_coverage_cell_days.parquet"
PILOT_TRACE_PATH = DATA_DIR / "metrics" / "philippines_hotspot_coverage_pilot_trace.json"
INVENTORY_PATH = DATA_DIR / "metrics" / "philippines_hotspot_granule_inventory.json"

# Frozen before rebuilding labels / comparing models.
HOTSPOT_DAILY_COVERAGE_RULE = {
    "version": "hotspot_daily_coverage_v2_1",
    "supersedes_label_negatives_from": "hotspot_coverage_v2",
    "products": ["MYD14/MYD03 (Aqua)", "VNP14IMG/VNP03IMG (Suomi-NPP)"],
    "cell_area_km2": 25.0,
    "min_visible_land_fraction": 0.5,
    "min_visible_land_km2": 12.5,
    "which_passes_count": (
        "Daytime fire+geolocation pairs only (solar zenith / local-hour daytime gate "
        "in settings). Nighttime and incomplete fire/geo feeds do not count."
    ),
    "visible_land": (
        "Clear land or detected fire pixels. Cloud, water, unknown, sun glint, "
        "bow-tie deletion, and unprocessed/missing pixels do not count."
    ),
    "pass_statement": (
        "A no-detection pass with visible land ≥ 12.5 km² (50% of the 5 km square) "
        "supports: no qualifying heat was detected in that square at that observation time."
    ),
    "daily_negative": (
        "Philippine local day [00:00, +24h) Asia/Manila has ≥1 usable no-detection pass "
        "for the square AND zero qualifying detections (FIRMS or fire-mask hotspots) "
        "anywhere in that square-day window."
    ),
    "daily_positive": (
        "≥1 qualifying FIRMS detection (or fire-mask hotspot) in the square during the "
        "Philippine day window — same as before."
    ),
    "daily_unknown": (
        "No usable daytime pass covering the square that day (cloudy / missing / "
        "incomplete retrieval / night-only), and no positive detection."
    ),
    "forecast_percentage_meaning": (
        "Chance of satellite-detected heat = estimated probability that MODIS or VIIRS "
        "will record ≥1 qualifying heat detection in this 5 km square during the next "
        "24 hours (Manila midnight issue). When evaluation is restricted to square-days "
        "with adequate fire-mask coverage, the percentage is calibrated on those "
        "adequately observed days only — cloudy unknowns are out of scope for scoring."
    ),
    "march_2019_policy": (
        "March 2019 granules may be used only when explicitly labeled as a reader smoke "
        "test; they are outside the 2023–2026 Maguindanao training windows."
    ),
}


def freeze_daily_coverage_rule(path: Path | None = None) -> dict[str, Any]:
    from vela.hotspot_forecast import RULES_PATH, freeze_rules

    payload = freeze_rules()
    payload["daily_coverage_rule"] = HOTSPOT_DAILY_COVERAGE_RULE
    payload["coverage_rule"] = {
        **payload.get("coverage_rule", {}),
        "version": "hotspot_coverage_v2_1",
        "negative": HOTSPOT_DAILY_COVERAGE_RULE["daily_negative"],
        "unknown": HOTSPOT_DAILY_COVERAGE_RULE["daily_unknown"],
        "positive": HOTSPOT_DAILY_COVERAGE_RULE["daily_positive"],
        "forecast_percentage_meaning": HOTSPOT_DAILY_COVERAGE_RULE["forecast_percentage_meaning"],
    }
    target = path or RULES_PATH
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _sensor_for_platform(platform: str) -> str:
    return "modis" if platform == "Aqua" else "viirs"


def process_fire_geo_pass(
    *,
    fire_path: Path,
    geo_path: Path,
    platform: str,
    when: datetime,
    bbox: dict | None = None,
) -> dict[str, Any]:
    """Aggregate one daytime fire+geo pair onto 5 km cells inside the study box."""

    cfg = settings()
    box = bbox or STUDY["bbox"]
    west, south, east, north = box["west"], box["south"], box["east"], box["north"]
    sensor = _sensor_for_platform(platform)
    pixel_km2 = float(cfg["modis_pixel_km2"] if sensor == "modis" else cfg["viirs_pixel_km2"])
    cell_area = float(cfg["cell_area_km2"])
    minimum = float(HOTSPOT_DAILY_COVERAGE_RULE["min_visible_land_fraction"])

    read = read_pass(fire_path, geo_path, (west, south, east, north), when, cfg)
    if not read.get("ok"):
        return {
            "ok": False,
            "reason": read.get("reason"),
            "platform": platform,
            "fire_file": fire_path.name,
            "geo_file": geo_path.name,
            "when_utc": when.isoformat(),
            "rows": [],
        }

    cells = aggregate(read["lon"], read["lat"], read["classes"], sensor)
    rows = []
    for key, counts in cells.items():
        x_index, y_index = unpack(key)
        lon, lat = center(x_index, y_index)
        visible = visible_km2(counts, pixel_km2, cell_area)
        fraction = visible / cell_area if cell_area else 0.0
        hot = hotspot_count(counts)
        ph_day = ph_day_for_utc(when.strftime("%Y-%m-%d"), when.strftime("%H:%M"))
        # Prefer local_date from longitude for consistency with Vela grid dates
        local = local_date(when, lon)
        usable = fraction + 1e-12 >= minimum
        if sum(counts.values()) == 0 or counts.get("missing", 0) == sum(counts.values()):
            status = "insufficient"
            usable = False
        elif usable and hot == 0:
            status = "ok_clear_zero"
        elif usable and hot > 0:
            status = "ok_with_heat"
        else:
            status = "insufficient"
        rows.append(
            {
                "cell_id": cell_identifier(x_index, y_index),
                "center_lon": lon,
                "center_lat": lat,
                "ph_date": local.isoformat(),
                "ph_date_from_utc_manila": ph_day,
                "platform": platform,
                "sensor": sensor,
                "pass_time_utc": when.isoformat(),
                "local_hour": local_hour(when, lon),
                "fire_file": fire_path.name,
                "geo_file": geo_path.name,
                "visible_land_km2": visible,
                "visible_land_fraction": fraction,
                "qualifying_detection_count": hot,
                "coverage_status": status,
                "usable_for_negative": bool(usable and hot == 0),
                "counts_json": json.dumps(counts, sort_keys=True),
                "cloud_pixels": int(counts.get("cloud", 0)),
                "clear_pixels": int(counts.get("clear", 0)),
                "missing_pixels": int(counts.get("missing", 0)),
            }
        )
    return {
        "ok": True,
        "reason": None,
        "platform": platform,
        "fire_file": fire_path.name,
        "geo_file": geo_path.name,
        "when_utc": when.isoformat(),
        "n_cells": len(rows),
        "usable_clear_zeros": sum(1 for r in rows if r["usable_for_negative"]),
        "usable_with_heat": sum(1 for r in rows if r["coverage_status"] == "ok_with_heat"),
        "insufficient": sum(1 for r in rows if r["coverage_status"] == "insufficient"),
        "rows": rows,
    }


def process_directory_single_platform(directory: Path, bbox: dict | None = None) -> dict[str, Any]:
    files = [str(p) for p in directory.rglob("*") if p.suffix.lower() in {".hdf", ".nc", ".h5", ".hdf5"}]
    passes, unrecognized = index_passes(files)
    ready, incomplete = complete_passes(passes)
    results = []
    all_rows = []
    for item in ready:
        when = item["when"]
        out = process_fire_geo_pass(
            fire_path=Path(item["fire"]),
            geo_path=Path(item["geo"]),
            platform=item["platform"],
            when=when,
            bbox=bbox,
        )
        results.append({k: v for k, v in out.items() if k != "rows"})
        all_rows.extend(out.get("rows") or [])
    return {
        "directory": str(directory),
        "complete_passes": len(ready),
        "incomplete_passes": len(incomplete),
        "unrecognized": unrecognized[:20],
        "pass_summaries": results,
        "rows": all_rows,
    }


def consolidate_daily_coverage(pass_rows: list[dict]) -> list[dict]:
    """One compact row per cell × Philippine date from possibly many passes."""

    if not pass_rows:
        return []
    frame = pd.DataFrame(pass_rows)
    out = []
    for (cell_id, ph_date), group in frame.groupby(["cell_id", "ph_date"]):
        usable = group[group["usable_for_negative"]]
        with_heat = group[group["coverage_status"] == "ok_with_heat"]
        best = group.sort_values("visible_land_fraction", ascending=False).iloc[0]
        if len(with_heat):
            status = "ok_with_heat"
            label_support = "positive_candidate"
        elif len(usable):
            status = "ok_clear_zero"
            label_support = "negative_supported"
            best = usable.sort_values("visible_land_fraction", ascending=False).iloc[0]
        else:
            status = "insufficient"
            label_support = "unknown"
        out.append(
            {
                "cell_id": cell_id,
                "ph_date": ph_date,
                "coverage_status": status,
                "label_support": label_support,
                "platform": best["platform"],
                "pass_time_utc": best["pass_time_utc"],
                "fire_file": best["fire_file"],
                "geo_file": best["geo_file"],
                "visible_land_km2": float(best["visible_land_km2"]),
                "visible_land_fraction": float(best["visible_land_fraction"]),
                "qualifying_detection_count": int(group["qualifying_detection_count"].sum()),
                "n_passes": int(len(group)),
                "usable_clear_zero_passes": int(len(usable)),
                "center_lon": float(best["center_lon"]),
                "center_lat": float(best["center_lat"]),
            }
        )
    return out


def save_coverage_rows(daily_rows: list[dict], path: Path | None = None) -> Path:
    target = path or COVERAGE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(daily_rows)
    if target.is_file() and len(new):
        old = pd.read_parquet(target)
        merged = pd.concat([old, new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["cell_id", "ph_date", "platform", "pass_time_utc"], keep="last")
        # Keep best daily consolidation
        daily = consolidate_daily_coverage(merged.to_dict(orient="records"))
        pd.DataFrame(daily).to_parquet(target, index=False)
    elif len(new):
        daily = consolidate_daily_coverage(new.to_dict(orient="records"))
        pd.DataFrame(daily).to_parquet(target, index=False)
    else:
        pd.DataFrame(columns=["cell_id", "ph_date", "coverage_status"]).to_parquet(target, index=False)
    return target


def load_coverage_keys() -> set[tuple[str, str]]:
    if not COVERAGE_PATH.is_file():
        return set()
    frame = pd.read_parquet(COVERAGE_PATH)
    if frame.empty:
        return set()
    usable = frame[frame["coverage_status"].isin(["ok_clear_zero", "ok_with_heat"])]
    return {(str(r.cell_id), str(r.ph_date)[:10]) for r in usable.itertuples()}


def load_negative_keys() -> set[tuple[str, str]]:
    if not COVERAGE_PATH.is_file():
        return set()
    frame = pd.read_parquet(COVERAGE_PATH)
    if frame.empty:
        return set()
    usable = frame[frame["label_support"] == "negative_supported"]
    return {(str(r.cell_id), str(r.ph_date)[:10]) for r in usable.itertuples()}
