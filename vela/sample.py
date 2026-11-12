"""Sample whole weeks before any granules are downloaded."""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from vela.geo import season_of
from vela.settings import data_dir, regions, settings
from vela.splits import split_for_year

MANIFEST_COLUMNS = (
    "region_id",
    "region_name",
    "landscape",
    "role",
    "development",
    "year",
    "season",
    "week_start",
    "week_end",
    "thursday",
    "quiet",
    "split",
    "west",
    "south",
    "east",
    "north",
    "products",
)


def weeks_in_year(year: int) -> list[tuple[date, date, date]]:
    """ISO weeks whose Thursday falls in `year`. Each item is Monday, Sunday, Thursday."""

    cursor = date(year, 1, 1)
    while cursor.weekday() != 3:
        cursor += timedelta(days=1)
    rows = []
    while cursor.year == year:
        monday = cursor - timedelta(days=3)
        sunday = monday + timedelta(days=6)
        rows.append((monday, sunday, cursor))
        cursor += timedelta(days=7)
    return rows


def build_manifest(seed: int | None = None, config: dict | None = None, region_list: list[dict] | None = None) -> list[dict]:
    cfg = config or settings()
    rng = random.Random(cfg["seed"] if seed is None else seed)
    start_year, end_year = cfg["overlap_years"]
    products = ",".join(cfg["products"].keys())
    rows = []
    for region in regions() if region_list is None else region_list:
        quiet_months = set(region["quiet_months"])
        for year in range(int(start_year), int(end_year) + 1):
            catalog = weeks_in_year(year)
            by_season = {name: [] for name in ("DJF", "MAM", "JJA", "SON")}
            for item in catalog:
                by_season[season_of(item[2].month)].append(item)
            chosen = []
            for season, items in by_season.items():
                if items:
                    chosen.append((season, rng.choice(items)))
            if not any(item[2].month in quiet_months for _, item in chosen):
                quiet_pool = [item for item in catalog if item[2].month in quiet_months]
                if quiet_pool:
                    pick = rng.choice(quiet_pool)
                    chosen.append((season_of(pick[2].month) + "-quiet", pick))
            for season, (monday, sunday, thursday) in chosen:
                rows.append(
                    {
                        "region_id": region["id"],
                        "region_name": region["name"],
                        "landscape": region["landscape"],
                        "role": region["role"],
                        "development": "yes" if region["role"] != "transfer" else "no",
                        "year": year,
                        "season": season.replace("-quiet", ""),
                        "week_start": monday.isoformat(),
                        "week_end": sunday.isoformat(),
                        "thursday": thursday.isoformat(),
                        "quiet": "yes" if thursday.month in quiet_months else "no",
                        "split": split_for_year(year, cfg),
                        "west": region["west"],
                        "south": region["south"],
                        "east": region["east"],
                        "north": region["north"],
                        "products": products,
                    }
                )
    return rows


def write_manifest(rows: list[dict], path: Path | None = None) -> Path:
    destination = path or (data_dir("manifests") / "sample_manifest.csv")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return destination
