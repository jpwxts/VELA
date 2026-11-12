"""Metadata-only size estimate for the global sampling plan. Nothing is downloaded."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import date, timedelta

import pandas as pd

from scripts.process_matched_passes import _index_raw, _resolve
from vela.calendar_metrics import summarize_week
from vela.discover import discover_week
from vela.geo import season_of
from vela.global_plan import (
    choose_budget_weeks,
    load_plan,
    proposed_regions,
    select_plan_weeks,
    summarize_batches,
)
from vela.pipeline import describe_granule
from vela.sample import MANIFEST_COLUMNS, build_manifest
from vela.settings import DATA_DIR, data_dir, regions, settings
from vela.storage import directory_bytes

WEEKS_PATH = DATA_DIR / "manifests" / "global_plan_weeks.csv"
CHECKPOINT = DATA_DIR / "catalog" / "global_search_checkpoint.json"
FILE_KEYS = ("modis_fire", "modis_geo", "viirs_fire", "viirs_geo")


def _read_manifest() -> list[dict]:
    with (DATA_DIR / "manifests" / "sample_manifest.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _week_start(value: str) -> str:
    day = date.fromisoformat(str(value)[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def _thursday(week_start: str) -> date:
    return date.fromisoformat(week_start) + timedelta(days=3)


def current_representation() -> list[dict]:
    frame = pd.read_parquet(DATA_DIR / "processed" / "paired_cells.parquet")
    by_id = {region["id"]: region for region in regions()}
    frame = frame.copy()
    frame["week_start"] = frame["local_date"].map(lambda value: _week_start(str(value)))
    rows = []
    for region in regions():
        part = frame[frame["region_id"] == region["id"]]
        usable_weeks = []
        positives = 0
        seasons = set()
        for week, group in part.groupby("week_start"):
            records = group.to_dict("records")
            summary = summarize_week(records, settings())
            if summary["coverage_status"] != "ok":
                continue
            if not (2013 <= _thursday(str(week)).year <= 2020):
                continue
            usable_weeks.append(str(week))
            positives += int(summary["modis_active_cell_days"])
            seasons.add(season_of(_thursday(str(week)).month))
        rows.append(
            {
                "region_id": region["id"],
                "region_name": region["name"],
                "landscape": region["landscape"],
                "role": region["role"],
                "usable_training_weeks": len(usable_weeks),
                "week_starts": usable_weeks,
                "seasons": sorted(seasons),
                "modis_positive_cell_days": positives,
            }
        )
    return rows


def _region_lookup() -> dict[str, dict]:
    found = {region["id"]: region for region in regions()}
    for region in proposed_regions():
        found[region["id"]] = region
    return found


def _write_weeks(weeks: list[dict]) -> None:
    WEEKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fields = list(MANIFEST_COLUMNS) + ["batch_id", "budget_eligible"]
    with WEEKS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(weeks)


def _search_week(week: dict, lookup: dict[str, dict], cached_names: dict[str, object]) -> dict:
    region = lookup[week["region_id"]]
    report, objects = discover_week(region, week["week_start"], week["week_end"], settings())
    files = {}
    unknown = []
    for candidate in report["candidate_daytime_passes"]:
        for key in FILE_KEYS:
            name = candidate.get(key)
            if not name or name in files or name in unknown:
                continue
            granule = objects.get(name)
            info = describe_granule(granule) if granule is not None else None
            if info and info.get("size_bytes") is not None:
                files[name] = int(info["size_bytes"])
            else:
                unknown.append(name)
    new_files = {name: size for name, size in files.items() if _resolve(name, cached_names) is None}
    return {
        "region_id": week["region_id"],
        "season": week["season"],
        "year": int(week["year"]),
        "week_start": week["week_start"],
        "week_end": week["week_end"],
        "batch_id": week["batch_id"],
        "budget_eligible": week["budget_eligible"],
        "candidate_daytime_passes": int(report["candidate_count"]),
        "matched_pass_bytes": sum(int(item["bytes"] or 0) for item in report["candidate_daytime_passes"]),
        "unique_file_bytes": sum(files.values()),
        "files": files,
        "unknown_size_files": unknown,
        "already_cached_files": sorted(set(files) - set(new_files)),
    }


def _load_checkpoint() -> dict:
    if CHECKPOINT.is_file():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"weeks": {}}


def _save_checkpoint(payload: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    plan = load_plan()
    representation = current_representation()
    print("Usable training coverage already on disk:")
    for row in representation:
        seasons = ", ".join(row["seasons"]) if row["seasons"] else "none"
        print(
            f"  {row['region_id']} {row['landscape']} role={row['role']}: "
            f"{row['usable_training_weeks']} usable weeks, seasons {seasons}, "
            f"{row['modis_positive_cell_days']} MODIS-positive cell-days"
        )
    proposed_manifest = build_manifest(42, region_list=proposed_regions(plan))
    manifest_path = data_dir("manifests") / "global_region_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(proposed_manifest)
    weeks = select_plan_weeks(_read_manifest() + proposed_manifest, seed=42, plan=plan)
    _write_weeks(weeks)
    print(f"Selected {len(weeks)} training-year weeks before the catalog search. Wrote {WEEKS_PATH}")
    lookup = _region_lookup()
    cached_names = _index_raw()
    checkpoint = _load_checkpoint()
    done = checkpoint["weeks"]
    for index, week in enumerate(weeks, start=1):
        key = f"{week['region_id']}|{week['week_start']}"
        if key in done:
            print(f"{index}/{len(weeks)} cached {key}", flush=True)
            continue
        print(f"{index}/{len(weeks)} searching {key}", flush=True)
        done[key] = _search_week(week, lookup, cached_names)
        checkpoint["weeks"] = done
        _save_checkpoint(checkpoint)
        item = done[key]
        print(
            f"  passes {item['candidate_daytime_passes']}, unique bytes {item['unique_file_bytes']}",
            flush=True,
        )
    results = {
        (item["region_id"], item["week_start"]): item
        for item in done.values()
        if (item["region_id"], item["week_start"]) in {(week["region_id"], week["week_start"]) for week in weeks}
    }
    batches = summarize_batches(weeks, results, plan)
    budget = choose_budget_weeks(weeks, results, int(plan["budget_bytes"]))
    current = directory_bytes(DATA_DIR)
    free = shutil.disk_usage(DATA_DIR).free
    for batch in batches:
        batch["estimated_new_download_gb"] = batch["unique_new_bytes"] / 1_000_000_000
        batch["peak_temporary_disk_bytes"] = current + batch["unique_new_bytes"]
        batch["peak_temporary_disk_gb"] = batch["peak_temporary_disk_bytes"] / 1_000_000_000
    no_coverage_regions = []
    for batch in batches:
        no_coverage_regions.extend(batch["regions_with_no_paired_coverage"])
    estimate = {
        "fire_counts_used": False,
        "download_started": False,
        "selected_before_catalog_search": True,
        "seed": 42,
        "budget_bytes": int(plan["budget_bytes"]),
        "current_representation": representation,
        "batches": batches,
        "regions_with_no_paired_coverage": no_coverage_regions,
        "budget_batch": {
            "unique_new_bytes": budget["unique_new_bytes"],
            "estimated_new_download_gb": budget["unique_new_bytes"] / 1_000_000_000,
            "unique_files": budget["unique_files"],
            "peak_temporary_disk_bytes": current + budget["unique_new_bytes"],
            "weeks": [
                {
                    "region_id": week["region_id"],
                    "season": week["season"],
                    "year": int(week["year"]),
                    "week_start": week["week_start"],
                    "week_end": week["week_end"],
                    "candidate_daytime_passes": week["candidate_daytime_passes"],
                    "new_bytes": week["new_bytes"],
                }
                for week in budget["weeks"]
            ],
            "stopped_before": None
            if budget["stopped_before"] is None
            else {
                "region_id": budget["stopped_before"]["region_id"],
                "week_start": budget["stopped_before"]["week_start"],
                "new_bytes": budget["stopped_before"]["new_bytes"],
                "candidate_daytime_passes": budget["stopped_before"]["candidate_daytime_passes"],
            },
        },
        "current_data_bytes": current,
        "disk_free_bytes": free,
    }
    out = data_dir("catalog") / "global_plan.json"
    out.write_text(json.dumps(estimate, indent=2), encoding="utf-8")
    print("Ranked batches:")
    for batch in batches:
        print(
            f"  {batch['rank']} {batch['batch_id']} passes={batch['paired_daytime_passes']} "
            f"new_gb={batch['estimated_new_download_gb']:.3f} "
            f"peak_gb={batch['peak_temporary_disk_gb']:.3f} "
            f"no_coverage={batch['regions_with_no_paired_coverage']}"
        )
    print(f"Budget batch bytes: {budget['unique_new_bytes']}")
    print(f"Regions with no paired coverage: {no_coverage_regions}")
    print("No granules were downloaded.")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
