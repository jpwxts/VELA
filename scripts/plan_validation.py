"""Metadata-only size estimate for preselected 2021–2022 validation weeks."""

from __future__ import annotations

import csv
import json

from vela.discover import discover_week
from vela.expansion import select_validation_weeks
from vela.settings import DATA_DIR, data_dir, region_by_id, settings


def _read_manifest():
    with (DATA_DIR / "manifests" / "sample_manifest.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _matched_bytes(report: dict) -> int:
    return sum(int(item["bytes"] or 0) for item in report["candidate_daytime_passes"])


def main() -> int:
    selection = select_validation_weeks(_read_manifest(), seed=42)
    manifest = data_dir("manifests")
    for name, rows in (("validation_primary.csv", selection["primary"]), ("validation_reserves.csv", selection["reserves"])):
        path = manifest / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(f"Preselected {len(selection['primary'])} validation weeks and {len(selection['reserves'])} reserves before searching.")
    queue = list(selection["primary"])
    reserves = list(selection["reserves"])
    searched = []
    used = set()
    while queue:
        row = queue.pop(0)
        key = (row["region_id"], row["week_start"])
        if key in used:
            continue
        used.add(key)
        region = region_by_id(row["region_id"])
        report, _objects = discover_week(region, row["week_start"], row["week_end"], settings())
        item = {
            "region_id": row["region_id"],
            "season": row["season"],
            "year": int(row["year"]),
            "week_start": row["week_start"],
            "week_end": row["week_end"],
            "quiet": row["quiet"],
            "candidate_daytime_passes": report["candidate_count"],
            "matched_pass_bytes": _matched_bytes(report),
            "catalog_bytes": report["estimated_transfer_bytes"],
            "role": "primary" if any(other["week_start"] == row["week_start"] and other["region_id"] == row["region_id"] for other in selection["primary"]) else "reserve",
        }
        searched.append(item)
        print(
            f"  {item['role']} {row['region_id']} {row['season']} {row['year']} quiet={row['quiet']}: "
            f"{report['candidate_count']} passes, {item['matched_pass_bytes']} bytes"
        )
        if report["candidate_count"] == 0:
            replacement = next((candidate for candidate in reserves if (candidate["region_id"], candidate["week_start"]) not in used and candidate["season"] == row["season"]), None)
            if replacement is None:
                replacement = next((candidate for candidate in reserves if (candidate["region_id"], candidate["week_start"]) not in used), None)
            if replacement is not None:
                print(f"    no paired coverage; next reserve is {replacement['region_id']} {replacement['week_start']}")
                queue.append(replacement)
            else:
                print("    no paired coverage, and the reserve list is exhausted")
    kept = [item for item in searched if item["candidate_daytime_passes"] > 0]
    quiet_kept = [item for item in kept if str(item["quiet"]).lower() in {"yes", "true", "1"}]
    estimate = {
        "fire_counts_used": False,
        "download_started": False,
        "searched": searched,
        "weeks_with_paired_coverage": kept,
        "quiet_weeks_kept": len(quiet_kept),
        "additional_matched_pass_bytes": sum(item["matched_pass_bytes"] for item in kept),
        "additional_catalog_bytes": sum(int(item["catalog_bytes"] or 0) for item in kept),
        "separate_from_training_expansion_bytes": 4838284930,
    }
    out = data_dir("catalog") / "validation_estimate.json"
    out.write_text(json.dumps(estimate, indent=2), encoding="utf-8")
    print(f"Additional validation matched-pass download: {estimate['additional_matched_pass_bytes']} bytes")
    print(f"Quiet weeks kept because they have paired passes: {len(quiet_kept)}")
    print("No validation granules were downloaded.")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
