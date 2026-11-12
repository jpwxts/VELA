"""Score the frozen candidates on 2021–2022 rows. This does not download or evaluate 2023–2024."""

from __future__ import annotations

import csv
import json

from vela.expansion import choose_validation_budget
from vela.settings import DATA_DIR
from vela.train import run_model_selection

BUDGET_BYTES = 5_000_000_000
PLAN = DATA_DIR / "catalog" / "global_plan.json"
WEEKS = DATA_DIR / "manifests" / "global_plan_weeks.csv"
ESTIMATE = DATA_DIR / "catalog" / "validation_estimate.json"
SELECTION = DATA_DIR / "models" / "model_selection.json"


def _budget_batch() -> list[dict]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    weeks = { (row["region_id"], row["week_start"]): row for row in csv.DictReader(WEEKS.open(encoding="utf-8")) }
    inspected = []
    for item in plan["budget_batch"]["weeks"]:
        source = weeks[(item["region_id"], item["week_start"])]
        inspected.append(
            {
                "region_id": item["region_id"],
                "season": item["season"],
                "year": int(item["year"]),
                "week_start": item["week_start"],
                "week_end": item["week_end"],
                "split": source["split"],
                "role": source["role"],
                "development": source["development"],
                "qualifies_for_2021_2022_validation": source["split"] == "tune" and int(item["year"]) in (2021, 2022),
                "new_bytes": item["new_bytes"],
                "candidate_daytime_passes": item["candidate_daytime_passes"],
            }
        )
    return inspected


def main() -> int:
    batch = _budget_batch()
    estimate = json.loads(ESTIMATE.read_text(encoding="utf-8"))
    primary = list(estimate["weeks_with_paired_coverage"])
    budget = choose_validation_budget(primary, BUDGET_BYTES)
    accepted = {(row["region_id"], row["week_start"]) for row in budget["weeks"]}
    remaining = [row for row in primary if (row["region_id"], row["week_start"]) not in accepted]
    report = run_model_selection(DATA_DIR / "processed" / "paired_cells.parquet")
    report["arnhem_zambia_batch"] = {
        "estimated_new_download_bytes": 4606396933,
        "download_started": False,
        "weeks": batch,
        "validation_weeks": [row for row in batch if row["qualifies_for_2021_2022_validation"]],
    }
    report["validation_priority"] = {
        "budget_bytes": BUDGET_BYTES,
        "fire_counts_used": False,
        "source": "existing 2021–2022 manifest order",
        "accepted_weeks": budget["weeks"],
        "accepted_bytes": budget["unique_new_bytes"],
        "stopped_before": budget["stopped_before"],
        "next_preselected_weeks": remaining,
        "reserved_years": [2023, 2024],
        "pantanal": "reserved",
        "download_started": False,
    }
    previously_trained = set(report["candidate_identifiers"]["logistic_regression"].get("training_regions") or [])
    for row in report["validation_priority"]["accepted_weeks"]:
        row["region_group"] = "previously_trained" if row["region_id"] in previously_trained else "new"
    SELECTION.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("Arnhem–Zambia batch")
    for row in batch:
        mark = "validation" if row["qualifies_for_2021_2022_validation"] else row["split"]
        print(f"  {row['region_id']} {row['week_start']} to {row['week_end']} {row['season']} {mark}")
    print(f"Validation weeks inside that batch: {len(report['arnhem_zambia_batch']['validation_weeks'])}")
    print("Validation priority inside 5 GB")
    for row in budget["weeks"]:
        print(f"  {row['region_id']} {row['week_start']} {row['matched_pass_bytes']} bytes")
    print(f"Accepted bytes: {budget['unique_new_bytes']}")
    if budget["stopped_before"]:
        stopped = budget["stopped_before"]
        print(f"Stopped before {stopped['region_id']} {stopped['week_start']} ({stopped['matched_pass_bytes']} bytes)")
    print(f"Scored weeks: {report['scored_weeks']}")
    print(f"Selection status: {report['selection_status']}")
    print(f"Chosen model: {report['chosen_model']}")
    print("Final test evaluated: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
