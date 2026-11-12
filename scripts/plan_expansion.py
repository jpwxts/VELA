"""Estimate the first expansion batch before any new granules are downloaded."""

from __future__ import annotations

import csv
import json
import shutil

from vela.discover import discover_week
from vela.expansion import select_first_expansion
from vela.settings import DATA_DIR, data_dir, region_by_id, settings
from vela.storage import directory_bytes


def _read_manifest():
    path = DATA_DIR / "manifests" / "sample_manifest.csv"
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    rows = _read_manifest()
    chosen = select_first_expansion(rows, seed=42, exclude_weeks={("cerrado", "2019-08-19")})
    batch_path = data_dir("manifests") / "expansion_batch.csv"
    with batch_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(chosen[0].keys()))
        writer.writeheader()
        writer.writerows(chosen)
    print(f"Selected {len(chosen)} weeks from the manifest before searching the catalog.")
    for row in chosen:
        print(f"  {row['region_id']} {row['season']} {row['year']} {row['week_start']} to {row['week_end']}")
    cfg = settings()
    weeks = []
    catalog_bytes = 0
    pass_bytes = 0
    unknown = 0
    for row in chosen:
        region = region_by_id(row["region_id"])
        report, _objects = discover_week(region, row["week_start"], row["week_end"], cfg)
        candidate_bytes = sum(int(item["bytes"] or 0) for item in report["candidate_daytime_passes"])
        unknown_candidates = sum(1 for item in report["candidate_daytime_passes"] if item.get("bytes") is None)
        catalog_bytes += int(report["estimated_transfer_bytes"] or 0)
        pass_bytes += candidate_bytes
        unknown += int(report["unknown_size_count"]) + unknown_candidates
        weeks.append(
            {
                "region_id": row["region_id"],
                "season": row["season"],
                "year": int(row["year"]),
                "week_start": row["week_start"],
                "week_end": row["week_end"],
                "unique_files": report["unique_files"],
                "candidate_daytime_passes": report["candidate_count"],
                "catalog_bytes": report["estimated_transfer_bytes"],
                "matched_pass_bytes": candidate_bytes,
                "unknown_size_count": report["unknown_size_count"],
            }
        )
        print(
            f"  catalog {report['unique_files']} files, {report['estimated_transfer_bytes']} bytes; "
            f"matched daytime passes {report['candidate_count']}, {candidate_bytes} bytes"
        )
    current = directory_bytes(DATA_DIR)
    free = shutil.disk_usage(DATA_DIR).free
    estimate = {
        "selected_before_catalog_search": True,
        "fire_counts_used": False,
        "batch": str(batch_path),
        "weeks": weeks,
        "additional_catalog_bytes": catalog_bytes,
        "additional_matched_pass_bytes": pass_bytes,
        "unknown_size_count": unknown,
        "current_data_bytes": current,
        "peak_disk_bytes_if_matched_passes_downloaded": current + pass_bytes,
        "peak_disk_bytes_if_every_listed_granule_downloaded": current + catalog_bytes,
        "disk_free_bytes": free,
        "download_started": False,
    }
    out = data_dir("catalog") / "expansion_estimate.json"
    out.write_text(json.dumps(estimate, indent=2), encoding="utf-8")
    print(f"Additional matched-pass download: {pass_bytes} bytes")
    print(f"Additional download if every listed granule is retrieved: {catalog_bytes} bytes")
    print(f"Current data folder: {current} bytes")
    print(f"Peak disk if matched passes are kept: {current + pass_bytes} bytes")
    print(f"Disk free now: {free} bytes")
    print("No granules were downloaded.")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
