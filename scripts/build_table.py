"""Build paired_cells.parquet from swaths already stored in data/raw."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from vela.pairing import parse_granule_name
from vela.pipeline import process_directory
from vela.settings import DATA_DIR, data_dir, region_by_id, regions, settings
from vela.tables import compact_shards, write_rows


def _region_for(path: Path, fallback: str | None) -> dict:
    for region in regions():
        if region["id"] in path.parts:
            return region
    if fallback:
        return region_by_id(fallback)
    return {
        "id": "custom",
        "name": "Custom area",
        "landscape": "",
        "role": "unspecified",
        "west": -180,
        "south": -90,
        "east": 180,
        "north": 90,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Harmonize downloaded swaths into paired cell-days.")
    parser.add_argument("--region", help="Region id used when a file is not inside a region folder")
    args = parser.parse_args()
    raw = DATA_DIR / "raw"
    grouped: dict[str, list[str]] = defaultdict(list)
    owners: dict[str, dict] = {}
    if raw.exists():
        for path in raw.rglob("*"):
            if not path.is_file() or parse_granule_name(path) is None:
                continue
            region = _region_for(path, args.region)
            grouped[region["id"]].append(str(path))
            owners[region["id"]] = region
    if not grouped:
        print(f"No swath files in {raw}. Run the one-pass verification or bulk acquisition first.")
        return 2
    cfg = settings()
    for region_id, files in grouped.items():
        region = owners[region_id]
        bbox = (region["west"], region["south"], region["east"], region["north"])
        print(f"Processing {len(files)} files for {region_id}")
        result = process_directory(files, bbox, region, cfg)
        rows = result["eligible"] + result["excluded"]
        if not rows:
            print(f"{region_id}: no cell rows. Skips: {result['granule_skips']}")
            continue
        destination = data_dir("processed", "shards") / f"{region_id}.parquet"
        write_rows(rows, destination)
        print(
            f"{region_id}: {len(result['eligible'])} eligible, "
            f"exclusions {result['exclusion_counts']}, outcomes {result['outcome_counts']}"
        )
    summary = compact_shards()
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
