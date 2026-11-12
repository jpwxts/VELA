"""Download one daytime pass from each platform and read the fire masks."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.messages import EARTHDATA_STEPS
from vela.discover import discover_week
from vela.pipeline import process_directory
from vela.readers import fire_histogram
from vela.settings import DATA_DIR, data_dir, region_by_id, settings
from vela.storage import StorageMeter
from vela.tables import choose_trace_row, compact_shards, write_pass_shard, write_trace


def _download(objects: dict, names: list[str], destination: Path) -> list[Path]:
    import earthaccess

    granules = [objects[name] for name in names]
    destination.mkdir(parents=True, exist_ok=True)
    saved = earthaccess.download(granules, str(destination))
    return [Path(path) for path in saved if path]


def run_smoke() -> int:
    cfg = settings()
    meter = StorageMeter(DATA_DIR)
    chosen = None
    objects = {}
    for week in cfg["smoke_weeks"]:
        region = region_by_id(week["region_id"])
        report, week_objects = discover_week(region, week["start"], week["end"], cfg)
        data_dir("catalog").joinpath("search_report.json").write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print(
            f"{region['name']} {week['start']} to {week['end']}: "
            f"{report['unique_files']} files, {report['candidate_count']} candidate passes, "
            f"{report['estimated_transfer_bytes']} bytes estimated, "
            f"{report['unknown_size_count']} sizes unknown."
        )
        if report["candidate_count"] == 0:
            print(
                "No daytime pair survived the time window, footprint check, and "
                f"30-minute tolerance. Rejections: {report['rejected']}."
            )
            print("Trying the next configured week.")
            continue
        chosen = (region, week, report)
        objects = week_objects
        break
    if chosen is None:
        print("No configured week produced a candidate pass.")
        return 2
    region, week, report = chosen
    if not report["earthdata_login"]:
        print(EARTHDATA_STEPS)
        return 2
    candidate = report["candidate_daytime_passes"][0]
    names = [candidate["modis_fire"], candidate["modis_geo"], candidate["viirs_fire"], candidate["viirs_geo"]]
    missing = [name for name in names if name not in objects]
    if missing:
        print(f"Catalog names were not in the earthaccess results: {missing}")
        return 2
    destination = DATA_DIR / "raw" / region["id"] / candidate["modis_time"][:10]
    print(f"Downloading one Aqua pass and one Suomi-NPP pass into {destination}")
    saved = _download(objects, names, destination)
    for path in saved:
        meter.add_download(path.stat().st_size)
    print(f"Bytes downloaded: {meter.downloaded}")
    checks = {}
    for path in saved:
        if path.name.startswith(("MYD14", "VNP14IMG")):
            checks[path.name] = fire_histogram(path)
            print(
                f"Read {checks[path.name]['format']} fire mask {path.name} "
                f"shape={checks[path.name]['shape']} pixels={checks[path.name]['pixels']}"
            )
    bbox = (region["west"], region["south"], region["east"], region["north"])
    processed = process_directory([str(path) for path in saved], bbox, region, cfg)
    rows = processed["eligible"] + processed["excluded"]
    if rows:
        write_pass_shard(rows, region["id"], candidate["modis_fire"])
        compact_shards()
    trace_row = choose_trace_row(processed["eligible"], processed["excluded"])
    trace = write_trace(trace_row, {"confirmed_passes": processed["confirmed_passes"]})
    storage = meter.report()
    summary = {
        "region_id": region["id"],
        "week": week,
        "candidate": candidate,
        "files": [str(path) for path in saved],
        "reader_checks": checks,
        "eligible_cells": len(processed["eligible"]),
        "excluded_cells": len(processed["excluded"]),
        "exclusion_counts": processed["exclusion_counts"],
        "outcome_counts": processed["outcome_counts"],
        "granule_skips": processed["granule_skips"],
        "confirmed_passes": processed["confirmed_passes"],
        "storage": storage,
        "trace": str(trace) if trace else None,
        "data_origin": "nasa",
    }
    report_path = data_dir("catalog") / "smoke_report.json"
    report_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    data_dir("metrics").joinpath("storage.json").write_text(json.dumps(storage, indent=2), encoding="utf-8")
    print(f"Eligible cell-days: {len(processed['eligible'])}")
    print(f"Excluded cell-days: {processed['exclusion_counts']}")
    print(f"Outcomes: {processed['outcome_counts']}")
    print(f"Peak data-folder size: {storage['peak_temporary_bytes']} bytes")
    print(f"Wrote {report_path}")
    return 0 if checks else 2


def main() -> int:
    return run_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
