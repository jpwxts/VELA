"""Download the estimated matched passes, one pair at a time, and checkpoint each shard."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.messages import EARTHDATA_STEPS
from scripts.process_matched_passes import _four, _index_raw, _resolve
from scripts.smoke_test import _download
from vela.discover import discover_week
from vela.pipeline import process_directory
from vela.serving import write_job
from vela.settings import DATA_DIR, data_dir, region_by_id, settings
from vela.tables import compact_shards, pass_shard_name, write_pass_shard

EXPECTED = {"cerrado": 5, "california": 5, "yakutia": 12}
PILOT_FILES = (
    DATA_DIR / "models" / "pilot_logistic_log1p.joblib",
    DATA_DIR / "models" / "pilot_report.json",
)
CHECKPOINT = DATA_DIR / "catalog" / "ingest_checkpoint.json"


def _fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_checkpoint() -> dict:
    if CHECKPOINT.is_file():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"completed": [], "bytes_downloaded": 0, "passes": [], "zambia": None}


def _save_checkpoint(payload: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _week_start(day: str) -> str:
    value = date.fromisoformat(str(day)[:10])
    monday = date.fromordinal(value.toordinal() - value.weekday())
    return monday.isoformat()


def _week_report(checkpoint: dict) -> list[dict]:
    paired = pd.read_parquet(DATA_DIR / "processed" / "paired_cells.parquet")
    excluded_path = DATA_DIR / "processed" / "excluded_cells.parquet"
    excluded = pd.read_parquet(excluded_path) if excluded_path.is_file() else paired.iloc[0:0]
    paired = paired.copy()
    excluded = excluded.copy()
    paired["week_start"] = paired["local_date"].astype(str).map(_week_start)
    if len(excluded):
        excluded["week_start"] = excluded["local_date"].astype(str).map(_week_start)
    rows = []
    keys = set(zip(paired["region_id"], paired["week_start"]))
    if len(excluded):
        keys.update(zip(excluded["region_id"], excluded["week_start"]))
    for region_id, week_start in sorted(keys):
        kept = paired[(paired["region_id"] == region_id) & (paired["week_start"] == week_start)]
        left = excluded[(excluded["region_id"] == region_id) & (excluded["week_start"] == week_start)] if len(excluded) else kept.iloc[0:0]
        files = set(kept["modis_file"].dropna().astype(str)) if len(kept) else set()
        if len(left) and "modis_file" in left.columns:
            files.update(left["modis_file"].dropna().astype(str))
        eligible_days = sorted(set(kept["local_date"].astype(str).str.slice(0, 10))) if len(kept) else []
        excluded_days = set(left["local_date"].astype(str).str.slice(0, 10)) if len(left) else set()
        reasons = left["exclusion_reason"].value_counts().to_dict() if len(left) else {}
        rows.append(
            {
                "region_id": region_id,
                "week_start": week_start,
                "matched_passes": len(files),
                "distinct_eligible_dates": len(eligible_days),
                "eligible_dates": eligible_days,
                "eligible_cell_days": int(len(kept)),
                "modis_positives": int(kept["modis_detected"].fillna(False).astype(bool).sum()) if len(kept) else 0,
                "viirs_positives": int((kept["viirs_hotspot_pixel_count"].astype(float) >= 1).sum()) if len(kept) else 0,
                "excluded_cells": int(len(left)),
                "excluded_coverage": {str(key): int(value) for key, value in reasons.items()},
                "insufficient_dates": [
                    {"local_date": day, "coverage_status": "insufficient", "rate": None}
                    for day in sorted(excluded_days - set(eligible_days))
                ],
            }
        )
    zambia = checkpoint.get("zambia")
    if zambia:
        rows.append(zambia)
    return rows


def main() -> int:
    pilots = {str(path): _fingerprint(path) for path in PILOT_FILES}
    checkpoint = _load_checkpoint()
    batch = list(pd.read_csv(DATA_DIR / "manifests" / "expansion_batch.csv").to_dict("records"))
    zambia = next(row for row in batch if row["region_id"] == "zambia")
    checkpoint["zambia"] = {
        "region_id": "zambia",
        "week_start": zambia["week_start"],
        "week_end": zambia["week_end"],
        "status": "no_paired_coverage",
        "matched_passes": 0,
        "distinct_eligible_dates": 0,
        "eligible_cell_days": 0,
        "modis_positives": 0,
        "viirs_positives": 0,
        "excluded_cells": 0,
        "excluded_coverage": {},
        "rate": None,
    }
    _save_checkpoint(checkpoint)
    print("Zambia 2020-08-17 to 2020-08-23: no paired coverage. No files downloaded.")
    cfg = settings()
    planned = []
    for row in batch:
        if row["region_id"] not in EXPECTED:
            continue
        region = region_by_id(row["region_id"])
        report, objects = discover_week(region, row["week_start"], row["week_end"], cfg)
        found = report["candidate_daytime_passes"]
        print(f"{row['region_id']}: catalog returned {len(found)} matched daytime passes.")
        if len(found) != EXPECTED[row["region_id"]]:
            print(f"Expected {EXPECTED[row['region_id']]} passes and will not download a different set.")
            return 2
        if not report["earthdata_login"]:
            print(EARTHDATA_STEPS)
            return 2
        for candidate in found:
            planned.append((region, candidate, objects))
    print(f"Retrieving {len(planned)} matched passes, one pair at a time.")
    completed = set(checkpoint["completed"])
    for number, (region, candidate, objects) in enumerate(planned, start=1):
        stamp = pass_shard_name(region["id"], candidate["modis_fire"])
        shard = DATA_DIR / "processed" / "shards" / stamp
        if stamp in completed or shard.is_file():
            print(f"Pass {number}/{len(planned)} already checkpointed: {stamp}")
            completed.add(stamp)
            continue
        index = _index_raw()
        names = _four(candidate)
        missing = [name for name in names if _resolve(name, index) is None]
        if missing:
            unknown = [name for name in missing if name not in objects]
            if unknown:
                print(f"Catalog names were not in the earthaccess results: {unknown}")
                return 2
            destination = DATA_DIR / "raw" / region["id"] / candidate["modis_time"][:10]
            print(f"Pass {number}/{len(planned)} downloading {len(missing)} files into {destination}", flush=True)
            before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
            saved = _download(objects, missing, destination)
            new_bytes = 0
            for path in saved:
                file_path = Path(path)
                if file_path.resolve() not in before:
                    new_bytes += file_path.stat().st_size
            checkpoint["bytes_downloaded"] = int(checkpoint["bytes_downloaded"]) + new_bytes
            _save_checkpoint(checkpoint)
            index = _index_raw()
        paths = []
        for name in names:
            found = _resolve(name, index)
            if found is None:
                print(f"Missing {name} after download.")
                return 2
            paths.append(str(found))
        print(f"Pass {number}/{len(planned)} reading {candidate['modis_fire']}", flush=True)
        write_job("ingest_expansion", number / len(planned), f"Reading {candidate['modis_fire']}")
        bbox = (region["west"], region["south"], region["east"], region["north"])
        processed = process_directory(paths, bbox, region, cfg)
        rows = processed["eligible"] + processed["excluded"]
        if rows:
            write_pass_shard(rows, region["id"], candidate["modis_fire"])
            compact = compact_shards()
            print(
                f"Pass {number}/{len(planned)} outcomes {processed['outcome_counts']}; "
                f"table now {compact['eligible']} eligible cell-days",
                flush=True,
            )
        else:
            print(f"Pass {number}/{len(planned)} produced no cells: {processed['granule_skips']}", flush=True)
        completed.add(stamp)
        checkpoint["completed"] = sorted(completed)
        checkpoint["passes"].append(
            {
                "region_id": region["id"],
                "stamp": stamp,
                "modis_fire": candidate["modis_fire"],
                "eligible": len(processed["eligible"]),
                "outcomes": processed["outcome_counts"],
                "exclusion_counts": processed["exclusion_counts"],
            }
        )
        _save_checkpoint(checkpoint)
    report_rows = _week_report(checkpoint)
    duplicates = int(pd.read_parquet(DATA_DIR / "processed" / "paired_cells.parquet").duplicated(["cell_id", "local_date"]).sum())
    summary = {
        "bytes_downloaded": int(checkpoint["bytes_downloaded"]),
        "duplicate_cell_days": duplicates,
        "weeks": report_rows,
        "pilot_unchanged": all(_fingerprint(Path(path)) == digest for path, digest in pilots.items()),
    }
    out = data_dir("catalog") / "expansion_weeks.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Bytes downloaded this expansion: {summary['bytes_downloaded']}")
    print(f"Duplicate cell-days: {duplicates}")
    print(f"Pilot files unchanged: {summary['pilot_unchanged']}")
    for row in report_rows:
        print(
            f"{row['region_id']} {row.get('week_start')} passes={row.get('matched_passes')} "
            f"dates={row.get('distinct_eligible_dates')} cells={row.get('eligible_cell_days')} "
            f"modis+={row.get('modis_positives')} viirs+={row.get('viirs_positives')} "
            f"excluded={row.get('excluded_cells')} status={row.get('status', 'ingested')}"
        )
    if not summary["pilot_unchanged"]:
        print("The saved pilot files changed. That was not intended.")
        return 2
    if duplicates:
        print("Duplicate cell-days were written.")
        return 2
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
