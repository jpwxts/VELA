"""Metadata-only transfer estimate for the preselected Yakutia validation week."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.process_matched_passes import _index_raw
from vela.discover import discover_week
from vela.pipeline import describe_granule
from vela.settings import DATA_DIR, region_by_id, settings


def main() -> int:
    region = region_by_id("yakutia")
    report, objects = discover_week(region, "2021-11-22", "2021-11-28", settings())
    index = _index_raw()
    sizes = {name: describe_granule(granule).get("size_bytes") for name, granule in objects.items()}
    files = {}
    for candidate in report["candidate_daytime_passes"]:
        for key in ("modis_fire", "modis_geo", "viirs_fire", "viirs_geo"):
            name = candidate[key]
            files[name] = sizes.get(name)
    cached = []
    missing = []
    unknown = []
    for name, size in files.items():
        present = index.get(name) or index.get(Path(name).stem)
        if present is not None:
            cached.append(name)
        elif size is None:
            unknown.append(name)
        else:
            missing.append((name, int(size)))
    payload = {
        "region_id": "yakutia",
        "week_start": "2021-11-22",
        "week_end": "2021-11-28",
        "split": "tune",
        "fire_counts_used": False,
        "download_started": False,
        "matched_passes": report["candidate_count"],
        "unique_matched_files": len(files),
        "cached_files": cached,
        "missing_files": len(missing),
        "unknown_size_files": unknown,
        "gross_matched_pass_bytes": sum(int(size) for size in files.values() if size is not None),
        "additional_transfer_bytes": sum(size for _name, size in missing),
        "prior_estimate_bytes": 3229215808,
    }
    destination = DATA_DIR / "catalog" / "yakutia_validation_estimate.json"
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "cached_files"}, indent=2))
    print(f"cached file count: {len(cached)}")
    print(destination)
    return 0 if not unknown else 2


if __name__ == "__main__":
    raise SystemExit(main())
