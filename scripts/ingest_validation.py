"""Download the estimated 2021–2022 matched passes. This does not select a model."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ingest_expansion import _fingerprint
from scripts.process_matched_passes import _four, _index_raw, _resolve
from scripts.smoke_test import _download
from vela.discover import discover_week
from vela.pipeline import process_directory
from vela.settings import DATA_DIR, data_dir, region_by_id, settings
from vela.tables import compact_shards, pass_shard_name, write_pass_shard

ESTIMATE = DATA_DIR / "catalog" / "validation_estimate.json"
CHECKPOINT = DATA_DIR / "catalog" / "validation_checkpoint.json"
PILOT_FILES = (
    DATA_DIR / "models" / "pilot_logistic_log1p.joblib",
    DATA_DIR / "models" / "pilot_report.json",
)


def _save(payload: dict) -> None:
    CHECKPOINT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    estimate = json.loads(ESTIMATE.read_text(encoding="utf-8"))
    weeks = [
        row
        for row in estimate["weeks_with_paired_coverage"]
        if row["region_id"] != "pantanal" and int(row["year"]) in (2021, 2022)
    ]
    pilots = {str(path): _fingerprint(path) for path in PILOT_FILES}
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8")) if CHECKPOINT.is_file() else {"completed": [], "bytes_downloaded": 0}
    cfg = settings()
    completed = set(checkpoint["completed"])
    for week in weeks:
        region = region_by_id(week["region_id"])
        report, objects = discover_week(region, week["week_start"], week["week_end"], cfg)
        print(f"{week['region_id']} {week['week_start']}: {report['candidate_count']} matched passes", flush=True)
        for candidate in report["candidate_daytime_passes"]:
            stamp = pass_shard_name(region["id"], candidate["modis_fire"])
            shard = DATA_DIR / "processed" / "shards" / stamp
            if stamp in completed or shard.is_file():
                print(f"  already checkpointed {stamp}", flush=True)
                completed.add(stamp)
                continue
            index = _index_raw()
            names = _four(candidate)
            missing = [name for name in names if _resolve(name, index) is None]
            if missing:
                destination = DATA_DIR / "raw" / region["id"] / candidate["modis_time"][:10]
                print(f"  downloading {len(missing)} files for {candidate['modis_fire']}", flush=True)
                before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
                saved = _download(objects, missing, destination)
                new_bytes = sum(path.stat().st_size for path in (Path(item) for item in saved) if path.resolve() not in before)
                checkpoint["bytes_downloaded"] = int(checkpoint.get("bytes_downloaded", 0)) + new_bytes
                _save(checkpoint)
                index = _index_raw()
            resolved = [_resolve(name, index) for name in names]
            if any(item is None for item in resolved):
                print(f"Missing a file for {candidate['modis_fire']}")
                return 2
            paths = [str(item) for item in resolved]
            processed = process_directory(paths, (region["west"], region["south"], region["east"], region["north"]), region, cfg)
            rows = processed["eligible"] + processed["excluded"]
            if rows:
                write_pass_shard(rows, region["id"], candidate["modis_fire"])
                compact_shards()
            completed.add(stamp)
            checkpoint["completed"] = sorted(completed)
            _save(checkpoint)
            print(f"  {stamp} eligible {len(processed['eligible'])}", flush=True)
    unchanged = all(_fingerprint(Path(path)) == digest for path, digest in pilots.items())
    print(f"Validation bytes downloaded: {checkpoint['bytes_downloaded']}")
    print(f"Pilot files unchanged: {unchanged}")
    print("Model selection was not run. 2023–2024 and Pantanal stayed out.")
    data_dir("catalog")
    return 0 if unchanged else 2


if __name__ == "__main__":
    raise SystemExit(main())
