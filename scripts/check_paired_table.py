"""Check the expanded paired table and recount one VIIRS fire-pixel cell from VIIRS alone."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta

import pandas as pd

from scripts.ingest_expansion import CHECKPOINT
from scripts.process_matched_passes import _index_raw, _resolve
from vela.harmonize import aggregate
from vela.masks import FIRE_CATEGORIES
from vela.readers import read_pass
from vela.settings import DATA_DIR, region_by_id, settings

PILOT_WEEK = ("cerrado", "2019-08-19")
AUDIT_PATH = DATA_DIR / "models" / "viirs_feature_audit.json"


def _week_start(value) -> str:
    day = date.fromisoformat(str(value)[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def _positives(frame: pd.DataFrame, column: str) -> int:
    if frame.empty:
        return 0
    if column == "modis_detected":
        return int(frame[column].fillna(False).astype(bool).sum())
    return int((frame[column].astype(float) >= 1).sum())


def _week_row(region_id: str, week: str, frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {
            "region_id": region_id,
            "week_start": week,
            "eligible_dates": [],
            "eligible_cell_days": 0,
            "modis_positives": 0,
            "viirs_positives": 0,
            "coverage_status": "missing",
            "rate": None,
        }
    dates = sorted(set(frame["local_date"].astype(str).str.slice(0, 10)))
    return {
        "region_id": region_id,
        "week_start": week,
        "eligible_dates": dates,
        "eligible_cell_days": int(len(frame)),
        "modis_positives": _positives(frame, "modis_detected"),
        "viirs_positives": _positives(frame, "viirs_hotspot_pixel_count"),
        "coverage_status": "ok",
        "rate": None,
    }


def _recount(row: pd.Series) -> dict:
    index = _index_raw()
    fire = _resolve(str(row["viirs_file"]), index)
    geo = _resolve(str(row["viirs_geo_file"]), index)
    if fire is None or geo is None:
        raise RuntimeError("The VIIRS fire mask or geolocation file is not on disk.")
    region = region_by_id(str(row["region_id"]))
    bbox = (region["west"], region["south"], region["east"], region["north"])
    opened = read_pass(fire, geo, bbox, None, settings())
    if not opened["ok"]:
        raise RuntimeError(f"VIIRS-only read failed: {opened['reason']}")
    cells = aggregate(opened["lon"], opened["lat"], opened["classes"], "viirs")
    counts = cells.get(int(row["cell_key"]), {})
    recounted = int(sum(int(counts.get(name, 0)) for name in FIRE_CATEGORIES))
    return {
        "cell_id": str(row["cell_id"]),
        "cell_key": int(row["cell_key"]),
        "region_id": str(row["region_id"]),
        "local_date": str(row["local_date"])[:10],
        "viirs_file": fire.name,
        "viirs_geo_file": geo.name,
        "modis_file_not_opened": str(row["modis_file"]),
        "stored_viirs_hotspot_pixel_count": int(row["viirs_hotspot_pixel_count"]),
        "recount_from_viirs_swath_only": recounted,
        "recount_classes": {name: int(counts.get(name, 0)) for name in (
            "fire_low", "fire_nominal", "fire_high", "clear", "cloud", "water", "unknown", "missing"
        )},
        "matches_stored_count": recounted == int(row["viirs_hotspot_pixel_count"]),
        "uses_modis_footprint": False,
    }


def _validation_cache() -> dict:
    manifest = DATA_DIR / "manifests" / "validation_primary.csv"
    with manifest.open(encoding="utf-8") as handle:
        weeks = list(csv.DictReader(handle))
    stamps = set()
    for row in weeks:
        if row["region_id"] == "pantanal" or int(row["year"]) not in (2021, 2022):
            continue
        start = date.fromisoformat(row["week_start"])
        end = date.fromisoformat(row["week_end"])
        day = start
        while day <= end:
            stamps.add(f"A{day.strftime('%Y%j')}")
            day += timedelta(days=1)
    cached = []
    root = DATA_DIR / "raw"
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and any(stamp in path.name for stamp in stamps):
                cached.append(str(path.relative_to(DATA_DIR)))
    estimate = json.loads((DATA_DIR / "catalog" / "validation_estimate.json").read_text(encoding="utf-8"))
    return {
        "validation_weeks": [
            {
                "region_id": row["region_id"],
                "season": row["season"],
                "year": int(row["year"]),
                "week_start": row["week_start"],
                "quiet": row["quiet"],
            }
            for row in weeks
            if row["region_id"] != "pantanal" and int(row["year"]) in (2021, 2022)
        ],
        "cached_files": cached,
        "additional_matched_pass_bytes": estimate["additional_matched_pass_bytes"] if not cached else None,
        "download_started": False,
    }


def main() -> int:
    paired = pd.read_parquet(DATA_DIR / "processed" / "paired_cells.parquet")
    excluded_path = DATA_DIR / "processed" / "excluded_cells.parquet"
    excluded = pd.read_parquet(excluded_path) if excluded_path.is_file() else paired.iloc[0:0]
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    paired = paired.copy()
    paired["week_start"] = paired["local_date"].map(_week_start)
    duplicates = int(paired.duplicated(["cell_id", "local_date"]).sum())
    class_sum = (
        paired["viirs_fire_low"].astype(int)
        + paired["viirs_fire_nominal"].astype(int)
        + paired["viirs_fire_high"].astype(int)
    )
    class_sum_matches = bool((class_sum == paired["viirs_hotspot_pixel_count"].astype(int)).all())
    weeks = []
    for (region_id, week), part in paired.groupby(["region_id", "week_start"], sort=True):
        weeks.append(_week_row(str(region_id), str(week), part))
    zambia = checkpoint.get("zambia") or {}
    if not any(row["region_id"] == "zambia" for row in weeks):
        weeks.append(
            {
                "region_id": "zambia",
                "week_start": zambia.get("week_start", "2020-08-17"),
                "eligible_dates": [],
                "eligible_cell_days": 0,
                "modis_positives": 0,
                "viirs_positives": 0,
                "coverage_status": "missing",
                "rate": None,
                "status": "no_paired_coverage",
            }
        )
    pilot_mask = (paired["region_id"] == PILOT_WEEK[0]) & (paired["week_start"] == PILOT_WEEK[1])
    pilot = paired[pilot_mask]
    added = paired[~pilot_mask]
    present_files = set()
    for frame in (paired, excluded):
        if "modis_file" in frame.columns and len(frame):
            present_files.update(frame["modis_file"].dropna().astype(str))
    if len(excluded):
        excluded = excluded.copy()
        excluded["week_start"] = excluded["local_date"].map(_week_start)
        for row in weeks:
            part = excluded[
                (excluded["region_id"] == row["region_id"]) & (excluded["week_start"] == row["week_start"])
            ]
            excluded_dates = set(part["local_date"].astype(str).str.slice(0, 10)) if len(part) else set()
            row["insufficient_dates"] = [
                {"local_date": day, "coverage_status": "insufficient", "rate": None}
                for day in sorted(excluded_dates - set(row["eligible_dates"]))
            ]
    pass_rows = []
    for item in checkpoint["passes"]:
        stem = str(item["modis_fire"])
        found = any(stem in name for name in present_files)
        shard = DATA_DIR / "processed" / "shards" / item["stamp"]
        pass_rows.append(
            {
                "stamp": item["stamp"],
                "modis_fire": stem,
                "rows_in_cell_tables": found,
                "shard_on_disk": shard.is_file(),
                "eligible_at_ingest": item["eligible"],
            }
        )
    sample = paired[(paired["region_id"] != "cerrado") & (paired["viirs_hotspot_pixel_count"].astype(int) > 0)].iloc[0]
    audit = _recount(sample)
    previous = json.loads(AUDIT_PATH.read_text(encoding="utf-8")) if AUDIT_PATH.is_file() else {}
    previous["expansion_cell"] = audit
    previous["eligible_rows_match_viirs_class_sum"] = class_sum_matches
    AUDIT_PATH.write_text(json.dumps(previous, indent=2), encoding="utf-8")
    batches = {
        "original_pilot": _week_row("cerrado", "2019-08-19", pilot),
        "expansion_rows": {
            "eligible_cell_days": int(len(added)),
            "modis_positives": _positives(added, "modis_detected"),
            "viirs_positives": _positives(added, "viirs_hotspot_pixel_count"),
            "eligible_dates": sorted(set(added["local_date"].astype(str).str.slice(0, 10))),
        },
        "combined": {
            "eligible_cell_days": int(len(paired)),
            "modis_positives": _positives(paired, "modis_detected"),
            "viirs_positives": _positives(paired, "viirs_hotspot_pixel_count"),
            "duplicate_cell_days": duplicates,
        },
    }
    report = {
        "downloaded_passes": len(checkpoint["passes"]),
        "passes_with_cell_rows": sum(1 for item in pass_rows if item["rows_in_cell_tables"]),
        "passes": pass_rows,
        "weeks": weeks,
        "batches": batches,
        "duplicate_cell_days": duplicates,
        "viirs_class_sum_matches_predictor": class_sum_matches,
        "viirs_recount_matches": audit["matches_stored_count"],
        "validation_cache": _validation_cache(),
    }
    destination = DATA_DIR / "catalog" / "paired_table_check.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "batches": batches,
        "weeks": weeks,
        "passes_with_cell_rows": report["passes_with_cell_rows"],
        "passes_without_rows": [item["modis_fire"] for item in pass_rows if not item["rows_in_cell_tables"]],
        "duplicate_cell_days": duplicates,
        "viirs_recount": audit,
        "cached_validation_files": report["validation_cache"]["cached_files"],
        "additional_matched_pass_bytes": report["validation_cache"]["additional_matched_pass_bytes"],
    }, indent=2))
    if duplicates or not class_sum_matches or not audit["matches_stored_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
