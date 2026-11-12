"""Download and score one reserve validation week after an unscorable attempted week.

This script does nothing until --i-authorize-download is passed. It does not
refit candidates, download NOAA granules, or open 2023–2024 or Pantanal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.process_matched_passes import _four, _index_raw, _resolve
from scripts.smoke_test import _download
from vela.discover import discover_week
from vela.pipeline import describe_granule, process_directory
from vela.settings import DATA_DIR, region_by_id, settings
from vela.tables import compact_shards, pass_shard_name, write_pass_shard


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--week-start", required=True)
    parser.add_argument("--week-end", required=True)
    parser.add_argument(
        "--i-authorize-download",
        action="store_true",
        help="Required. Without this flag the script only prints the inventory path.",
    )
    args = parser.parse_args()
    inventory = DATA_DIR / "catalog" / f"{args.region}_reserve_inventory.json"
    if args.region == "arnhem" and args.week_start == "2022-11-28":
        inventory = DATA_DIR / "catalog" / "arnhem_reserve_inventory.json"
    if not args.i_authorize_download:
        print(
            "Download is not authorized. Re-run with --i-authorize-download after review. "
            f"Inventory: {inventory}"
        )
        return 2
    if args.region == "pantanal" or args.week_start.startswith(("2023", "2024")):
        raise RuntimeError("The reserved final test and Pantanal stay closed.")
    cfg = settings()
    region = region_by_id(args.region)
    report, objects = discover_week(region, args.week_start, args.week_end, cfg)
    sizes = {name: describe_granule(granule).get("size_bytes") for name, granule in objects.items()}
    checkpoint_path = DATA_DIR / "catalog" / f"{args.region}_{args.week_start}_checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.is_file() else {
        "completed": [],
        "bytes_downloaded": 0,
    }
    index = _index_raw()
    for candidate in report["candidate_daytime_passes"]:
        stamp = pass_shard_name(region["id"], candidate["modis_fire"])
        names = _four(candidate)
        missing = [name for name in names if _resolve(name, index) is None]
        destination = DATA_DIR / "raw" / region["id"] / str(candidate["modis_time"])[:10]
        if missing:
            before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
            saved = _download(objects, missing, destination)
            new_bytes = sum(
                path.stat().st_size
                for path in (Path(item) for item in saved)
                if path.resolve() not in before
            )
            checkpoint["bytes_downloaded"] = int(checkpoint.get("bytes_downloaded", 0)) + new_bytes
            checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
            index = _index_raw()
        resolved = [_resolve(name, index) for name in names]
        if any(item is None for item in resolved):
            print(f"Missing a file for {candidate['modis_fire']}")
            return 2
        if stamp not in set(checkpoint.get("completed") or []):
            processed = process_directory(
                [str(item) for item in resolved],
                (region["west"], region["south"], region["east"], region["north"]),
                region,
                cfg,
            )
            rows = processed["eligible"] + processed["excluded"]
            if rows:
                write_pass_shard(rows, region["id"], candidate["modis_fire"])
                compact_shards()
            checkpoint.setdefault("completed", []).append(stamp)
            checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
            print(stamp, "eligible", len(processed["eligible"]), "excluded", len(processed["excluded"]))
        print("sizes known", sum(1 for name in names if sizes.get(name) is not None))
    print(f"Transferred bytes: {checkpoint.get('bytes_downloaded', 0)}")
    print("Score the frozen candidates with the existing selection helpers after this download.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
