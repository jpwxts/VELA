"""Search one configured week, and a second week if the first has no daytime pairs."""

from __future__ import annotations

import json

from vela.discover import discover_week
from vela.settings import data_dir, region_by_id, settings


def _print_report(report: dict) -> None:
    print(f"\nRegion: {report['region_name']} ({report['region_id']})")
    print(f"Week: {report['start']} to {report['end']}")
    print(f"Earthdata login: {'yes' if report['earthdata_login'] else 'no'}")
    print(f"Unique files: {report['unique_files']}")
    print(f"Files per product: {report['files_per_product']}")
    print(f"Candidate daytime passes: {report['candidate_count']}")
    if report["candidate_daytime_passes"]:
        first = report["candidate_daytime_passes"][0]
        print(f"First pass transfer: {first.get('bytes')} bytes ({first['modis_time']} and {first['viirs_time']})")
    print(f"Estimated transfer of every listed file: {report['estimated_transfer_bytes']} bytes")
    print(f"Files with unknown size: {report['unknown_size_count']}")
    print(f"Fire/geolocation pairs missing one file: {report['incomplete_fire_geo_pairs']}")
    print(f"MODIS passes without a VIIRS partner: {report['modis_passes_without_viirs']}")
    print(f"VIIRS passes without a MODIS partner: {report['viirs_passes_without_modis']}")
    print(f"Rejected before a candidate was kept: {report['rejected']}")
    if report.get("search_errors"):
        print(f"Search errors: {report['search_errors']}")
    if report["candidate_count"] == 0:
        print("No candidate daytime pass. Reasons are the partner and rejection counts above.")


def search_configured_weeks() -> list[dict]:
    cfg = settings()
    reports = []
    for week in cfg["smoke_weeks"]:
        region = region_by_id(week["region_id"])
        report, _objects = discover_week(region, week["start"], week["end"], cfg)
        reports.append(report)
        _print_report(report)
        if report["candidate_count"] > 0:
            break
        print("Trying the next configured week.")
    destination = data_dir("catalog") / "search_report.json"
    destination.write_text(json.dumps({"weeks": reports}, indent=2), encoding="utf-8")
    print(f"\nWrote {destination}")
    return reports


def main() -> int:
    reports = search_configured_weeks()
    return 0 if any(item["candidate_count"] > 0 for item in reports) else 2


if __name__ == "__main__":
    raise SystemExit(main())
