"""Choose a small 2013–2020 expansion from the manifest, without using fire counts."""

from __future__ import annotations

import random

SEASONS = ("DJF", "MAM", "JJA", "SON")


def select_first_expansion(rows: list[dict], *, seed: int = 42, exclude_weeks: set[tuple[str, str]] | None = None) -> list[dict]:
    """Pick one whole week in each season, rotating through non-reserved regions.

    The choice uses the manifest fields region, year, season, split, and role.
    It does not read hotspot counts or fire masks.
    """

    blocked = exclude_weeks or set()
    pool = []
    for row in rows:
        if row.get("role") == "transfer" or row.get("region_id") == "pantanal" or row.get("development") == "no":
            continue
        if row.get("split") != "train":
            continue
        year = int(row["year"])
        if year < 2013 or year > 2020 or row.get("season") not in SEASONS:
            continue
        if (row["region_id"], row["week_start"]) in blocked:
            continue
        pool.append(row)
    regions: list[str] = []
    for row in pool:
        if row["region_id"] not in regions:
            regions.append(row["region_id"])
    if len(regions) < 2:
        raise RuntimeError("The manifest does not have two non-reserved training regions.")
    rng = random.Random(seed)
    chosen = []
    used_years: set[int] = set()
    for index, season in enumerate(SEASONS):
        region = regions[index % len(regions)]
        candidates = [
            row
            for row in pool
            if row["region_id"] == region and row["season"] == season and int(row["year"]) not in used_years
        ]
        if not candidates:
            candidates = [row for row in pool if row["region_id"] == region and row["season"] == season]
        if not candidates:
            raise RuntimeError(f"No 2013–2020 manifest week for {region} in {season}.")
        pick = rng.choice(candidates)
        chosen.append(pick)
        used_years.add(int(pick["year"]))
    return chosen


def select_validation_weeks(rows: list[dict], *, seed: int = 42) -> dict:
    """Preselect 2021–2022 weeks, then a fixed reserve list. No fire counts are read."""

    pool = []
    for row in rows:
        if row.get("role") == "transfer" or row.get("region_id") == "pantanal" or row.get("development") == "no":
            continue
        if row.get("split") != "tune":
            continue
        year = int(row["year"])
        if year < 2021 or year > 2022 or row.get("season") not in SEASONS:
            continue
        pool.append(row)
    regions: list[str] = []
    for row in pool:
        if row["region_id"] not in regions:
            regions.append(row["region_id"])
    rng = random.Random(seed)
    primary = []
    used = set()
    slot = 0
    for year in (2021, 2022):
        for season in SEASONS:
            region = regions[slot % len(regions)] if regions else None
            slot += 1
            candidates = [
                row
                for row in pool
                if row["region_id"] == region and row["season"] == season and int(row["year"]) == year
            ]
            if not candidates:
                continue
            pick = rng.choice(candidates)
            primary.append(pick)
            used.add((pick["region_id"], pick["week_start"]))
    reserves = [
        row
        for row in sorted(pool, key=lambda item: (SEASONS.index(item["season"]), item["region_id"], int(item["year"])))
        if (row["region_id"], row["week_start"]) not in used
    ]
    return {"primary": primary, "reserves": reserves}


def choose_validation_budget(weeks: list[dict], budget_bytes: int = 5_000_000_000) -> dict:
    """Keep whole preselected weeks, in the order given, until the next week would exceed the budget.

    A week with no paired daytime pass is recorded and does not stop the walk.
    The walk stops before an oversized week instead of skipping ahead to a later smaller one.
    Matched-pass sizes may be used. Fire counts are not read.
    """

    accepted = []
    no_coverage = []
    running = 0
    stopped = None
    for week in weeks:
        passes = int(week.get("candidate_daytime_passes") or 0)
        size = int(week.get("matched_pass_bytes") or 0)
        if passes <= 0:
            no_coverage.append(week)
            continue
        if running + size > budget_bytes:
            stopped = {**week, "matched_pass_bytes": size}
            break
        running += size
        accepted.append(week)
    return {
        "budget_bytes": budget_bytes,
        "weeks": accepted,
        "no_paired_coverage_weeks": no_coverage,
        "unique_new_bytes": running,
        "stopped_before": stopped,
        "fire_counts_used": False,
    }
