"""Download whole manifest weeks. This is separate from the one-pass check."""

from __future__ import annotations

import argparse
import csv

from scripts.messages import EARTHDATA_STEPS
from scripts.smoke_test import _download
from vela.discover import discover_week
from vela.pipeline import process_directory
from vela.settings import DATA_DIR, data_dir, settings
from vela.storage import StorageMeter
from vela.tables import compact_shards, write_rows


def _read_manifest(path):
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch manifest weeks after printing the transfer estimate.")
    parser.add_argument("--download", action="store_true", help="Download after showing the estimate")
    parser.add_argument("--limit-weeks", type=int, default=1)
    parser.add_argument("--region")
    parser.add_argument("--include-transfer", action="store_true")
    args = parser.parse_args()
    manifest = DATA_DIR / "manifests" / "sample_manifest.csv"
    if not manifest.is_file():
        print("No manifest. Run: python -m scripts.make_manifest")
        return 2
    rows = _read_manifest(manifest)
    selected = []
    for row in rows:
        if args.region and row["region_id"] != args.region:
            continue
        if row["development"] != "yes" and not args.include_transfer:
            continue
        selected.append(row)
    selected = selected[: max(args.limit_weeks, 0)]
    if not selected:
        print("No manifest weeks matched.")
        return 2
    cfg = settings()
    meter = StorageMeter(DATA_DIR)
    login_known = False
    for row in selected:
        region = {
            "id": row["region_id"],
            "name": row["region_name"],
            "landscape": row["landscape"],
            "role": row["role"],
            "west": float(row["west"]),
            "south": float(row["south"]),
            "east": float(row["east"]),
            "north": float(row["north"]),
        }
        report, objects = discover_week(region, row["week_start"], row["week_end"], cfg)
        login_known = report["earthdata_login"]
        print(
            f"{row['region_id']} {row['week_start']} {row['split']} quiet={row['quiet']}: "
            f"{report['unique_files']} files, about {report['estimated_transfer_bytes']} bytes, "
            f"{report['unknown_size_count']} sizes unknown, {report['candidate_count']} daytime pairs."
        )
        if not args.download:
            continue
        if not login_known:
            print(EARTHDATA_STEPS)
            return 2
        names = []
        for candidate in report["candidate_daytime_passes"]:
            names.extend(
                [
                    candidate["modis_fire"],
                    candidate["modis_geo"],
                    candidate["viirs_fire"],
                    candidate["viirs_geo"],
                ]
            )
        names = [name for name in dict.fromkeys(names) if name in objects]
        if not names:
            print("No downloadable daytime pair for this week.")
            continue
        destination = DATA_DIR / "raw" / row["region_id"] / row["week_start"]
        saved = _download(objects, names, destination)
        for path in saved:
            meter.add_download(path.stat().st_size)
        bbox = (region["west"], region["south"], region["east"], region["north"])
        processed = process_directory([str(path) for path in saved], bbox, region, cfg)
        table_rows = processed["eligible"] + processed["excluded"]
        if table_rows:
            write_rows(table_rows, data_dir("processed", "shards") / f"{row['region_id']}_{row['week_start']}.parquet")
    if args.download:
        print(compact_shards())
        print(meter.report())
    else:
        print("Metadata only. Add --download to retrieve these weeks.")
    data_dir("metrics").joinpath("storage.json").write_text(
        __import__("json").dumps(meter.report(), indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
