"""Choose global sampling weeks before any fire count or granule search."""

from __future__ import annotations

import json
import random
from pathlib import Path

from vela.geo import boxes_overlap
from vela.settings import CONFIG_DIR

SEASONS = ("DJF", "MAM", "JJA", "SON")
PLAN_PATH = CONFIG_DIR / "global_regions.json"


def load_plan(path: Path | None = None) -> dict:
    return json.loads((path or PLAN_PATH).read_text(encoding="utf-8"))


def proposed_regions(plan: dict | None = None) -> list[dict]:
    return list((plan or load_plan())["regions"])


def batch_definitions(plan: dict | None = None) -> list[dict]:
    rows = list((plan or load_plan())["batches"])
    return sorted(rows, key=lambda item: int(item["rank"]))


def region_order(plan: dict | None = None) -> list[str]:
    ordered = []
    for batch in batch_definitions(plan):
        ordered.extend(batch["regions"])
    return ordered


def select_plan_weeks(rows: list[dict], *, seed: int = 42, plan: dict | None = None) -> list[dict]:
    """One 2013–2020 week per season, in the predeclared region order.

    The random draw uses only region, season, year, and split. It does not
    read fire counts. Reserved regions are included so their coverage can be
    checked, and they are marked ineligible for the training budget.
    """

    spec = plan or load_plan()
    eligible = {batch["id"]: bool(batch["budget_eligible"]) for batch in batch_definitions(spec)}
    region_batch = {}
    for batch in batch_definitions(spec):
        for region_id in batch["regions"]:
            region_batch[region_id] = batch["id"]
    rng = random.Random(seed)
    chosen = []
    for region_id in region_order(spec):
        pool = [row for row in rows if row["region_id"] == region_id and row["split"] == "train"]
        used_years: set[int] = set()
        batch_id = region_batch[region_id]
        for season in SEASONS:
            candidates = [
                row for row in pool if row["season"] == season and int(row["year"]) not in used_years
            ]
            if not candidates:
                candidates = [row for row in pool if row["season"] == season]
            if not candidates:
                continue
            pick = dict(rng.choice(candidates))
            pick["batch_id"] = batch_id
            pick["budget_eligible"] = "yes" if eligible[batch_id] else "no"
            chosen.append(pick)
            used_years.add(int(pick["year"]))
    return chosen


def _week_key(row: dict) -> tuple[str, str]:
    return (row["region_id"], row["week_start"])


def choose_budget_weeks(weeks: list[dict], results: dict[tuple[str, str], dict], budget_bytes: int) -> dict:
    """Add whole weeks in plan order until the next week would pass the budget.

    A week with no paired daytime pass adds nothing and does not stop the batch.
    File names already counted earlier in the batch are not counted again.
    """

    accepted = []
    no_coverage = []
    running = 0
    seen: dict[str, int] = {}
    stopped = None
    for week in weeks:
        if str(week.get("budget_eligible", "yes")) != "yes":
            continue
        result = results[_week_key(week)]
        passes = int(result.get("candidate_daytime_passes") or 0)
        files = dict(result.get("files") or {})
        if passes <= 0:
            no_coverage.append({**week, **result})
            continue
        if not files:
            stopped = {**week, **result, "new_bytes": None}
            break
        extra_files = {name: int(size) for name, size in files.items() if name not in seen}
        extra = sum(extra_files.values())
        if running + extra > budget_bytes:
            stopped = {**week, **result, "new_bytes": extra}
            break
        seen.update(extra_files)
        running += extra
        accepted.append({**week, **result, "new_bytes": extra})
    return {
        "weeks": accepted,
        "no_paired_coverage_weeks": no_coverage,
        "unique_new_bytes": running,
        "unique_files": len(seen),
        "stopped_before": stopped,
        "budget_bytes": budget_bytes,
    }


def summarize_batches(weeks: list[dict], results: dict[tuple[str, str], dict], plan: dict | None = None) -> list[dict]:
    spec = plan or load_plan()
    summaries = []
    for batch in batch_definitions(spec):
        members = [week for week in weeks if week["batch_id"] == batch["id"]]
        files: dict[str, int] = {}
        passes = 0
        regions_without_pairs = []
        for region_id in batch["regions"]:
            region_weeks = [week for week in members if week["region_id"] == region_id]
            region_passes = 0
            for week in region_weeks:
                result = results[_week_key(week)]
                region_passes += int(result.get("candidate_daytime_passes") or 0)
                passes += int(result.get("candidate_daytime_passes") or 0)
                for name, size in (result.get("files") or {}).items():
                    files.setdefault(name, int(size))
            if region_weeks and region_passes == 0:
                regions_without_pairs.append(region_id)
        summaries.append(
            {
                "rank": int(batch["rank"]),
                "batch_id": batch["id"],
                "name": batch["name"],
                "adds": batch["adds"],
                "budget_eligible": bool(batch["budget_eligible"]),
                "regions": list(batch["regions"]),
                "weeks": len(members),
                "paired_daytime_passes": passes,
                "unique_new_bytes": sum(files.values()),
                "unique_files": len(files),
                "regions_with_no_paired_coverage": regions_without_pairs,
            }
        )
    return summaries


def overlapping_pairs(regions: list[dict]) -> list[tuple[str, str]]:
    hits = []
    for index, left in enumerate(regions):
        left_box = (left["west"], left["south"], left["east"], left["north"])
        for right in regions[index + 1 :]:
            right_box = (right["west"], right["south"], right["east"], right["north"])
            if boxes_overlap(left_box, right_box):
                hits.append((left["id"], right["id"]))
    return hits
