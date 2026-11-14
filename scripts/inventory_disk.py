"""Measure on-disk Vela storage. Counts each physical file once (by inode)."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

from vela.settings import DATA_DIR, ROOT


def _classify_raw(name: str) -> str:
    upper = name.upper()
    if upper.startswith(("MYD14", "MOD14", "VNP14", "VJ114", "VJ214")) or "14IMG" in upper:
        return "raw_fire"
    if upper.startswith(("MYD03", "MOD03", "VNP03", "VJ103", "VJ203")) or "03IMG" in upper:
        return "raw_geolocation"
    return "raw_other"


def _unique_bytes(path: Path) -> tuple[int, int]:
    seen: set[tuple[int, int]] = set()
    total = 0
    files = 0
    if not path.exists():
        return 0, 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        files += 1
        key = (stat.st_dev, stat.st_ino)
        if key in seen:
            continue
        seen.add(key)
        total += stat.st_size
    return total, files


def inventory() -> dict:
    raw = DATA_DIR / "raw"
    by_region_type: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"bytes": 0, "files": 0}))
    basename_regions: dict[str, set[str]] = defaultdict(set)
    seen_inode: set[tuple[int, int]] = set()
    unique_raw_bytes = 0
    unique_raw_files = 0

    if raw.exists():
        for path in raw.rglob("*"):
            if not path.is_file():
                continue
            if path.parts and "_quarantine" in path.as_posix():
                # Quarantine is reported separately.
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(raw)
            region = rel.parts[0] if rel.parts else "unknown"
            if region.startswith("_"):
                continue
            kind = _classify_raw(path.name)
            by_region_type[region][kind]["bytes"] += stat.st_size
            by_region_type[region][kind]["files"] += 1
            basename_regions[path.name].add(region)
            key = (stat.st_dev, stat.st_ino)
            if key not in seen_inode:
                seen_inode.add(key)
                unique_raw_bytes += stat.st_size
                unique_raw_files += 1

    shared_basenames = {
        name: sorted(regions)
        for name, regions in basename_regions.items()
        if len(regions) > 1
    }

    buckets = {
        "raw_fire_granules": 0,
        "raw_geolocation_granules": 0,
        "processed_tables": _unique_bytes(DATA_DIR / "processed")[0],
        "model_artifacts": _unique_bytes(DATA_DIR / "models")[0],
        "demo_test_fixtures": _unique_bytes(DATA_DIR / "fixtures")[0],
        "manifests": _unique_bytes(DATA_DIR / "manifests")[0],
        "catalog": _unique_bytes(DATA_DIR / "catalog")[0],
        "cache": _unique_bytes(DATA_DIR / "cache")[0],
    }
    for region_kinds in by_region_type.values():
        buckets["raw_fire_granules"] += region_kinds.get("raw_fire", {}).get("bytes", 0)
        buckets["raw_geolocation_granules"] += region_kinds.get("raw_geolocation", {}).get("bytes", 0)
        buckets["raw_fire_granules"] += region_kinds.get("raw_other", {}).get("bytes", 0)

    region_totals = []
    for region, kinds in sorted(by_region_type.items()):
        total = sum(item["bytes"] for item in kinds.values())
        files = sum(item["files"] for item in kinds.values())
        region_totals.append(
            {
                "region_id": region,
                "bytes": total,
                "gb": round(total / 1e9, 3),
                "files": files,
                "by_type": {
                    kind: {"bytes": info["bytes"], "gb": round(info["bytes"] / 1e9, 3), "files": info["files"]}
                    for kind, info in sorted(kinds.items())
                },
            }
        )
    region_totals.sort(key=lambda item: item["bytes"], reverse=True)

    usage = shutil.disk_usage(ROOT)
    largest = []
    for path in [DATA_DIR, DATA_DIR / "raw", DATA_DIR / "processed", DATA_DIR / "models", DATA_DIR / "fixtures"]:
        nbytes, nfiles = _unique_bytes(path)
        largest.append({"path": str(path.relative_to(ROOT)), "bytes": nbytes, "gb": round(nbytes / 1e9, 3), "files": nfiles})
    if raw.exists():
        for child in raw.iterdir():
            if child.is_dir() and not child.name.startswith("_"):
                nbytes, nfiles = _unique_bytes(child)
                largest.append(
                    {
                        "path": str(child.relative_to(ROOT)),
                        "bytes": nbytes,
                        "gb": round(nbytes / 1e9, 3),
                        "files": nfiles,
                    }
                )
    largest.sort(key=lambda item: item["bytes"], reverse=True)

    return {
        "disk": {
            "path": str(ROOT),
            "total_gb": round(usage.total / 1e9, 2),
            "used_gb": round(usage.used / 1e9, 2),
            "free_gb": round(usage.free / 1e9, 2),
        },
        "counting_rule": "Each physical file counted once by (device, inode). No hard-linked duplicates found across regions.",
        "unique_raw": {"files": unique_raw_files, "bytes": unique_raw_bytes, "gb": round(unique_raw_bytes / 1e9, 3)},
        "shared_basenames_across_regions": shared_basenames,
        "shared_basename_count": len(shared_basenames),
        "by_file_type_gb": {key: round(value / 1e9, 3) for key, value in buckets.items()},
        "by_file_type_bytes": buckets,
        "by_region": region_totals,
        "largest_directories": largest[:15],
    }


def main() -> int:
    report = inventory()
    out = DATA_DIR / "metrics" / "disk_inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["disk"], indent=2))
    print("Wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
