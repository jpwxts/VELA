"""Retrieve the three preselected 2021 validation weeks and score the frozen candidates.

This does not refit a model and does not open Yakutia, 2023–2024, or Pantanal.
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from scripts.ingest_expansion import _fingerprint
from scripts.process_matched_passes import _four, _index_raw, _resolve
from scripts.smoke_test import _download
from vela.calendar_metrics import insufficient_reason, summarize_week
from vela.discover import discover_week
from vela.pipeline import describe_granule, process_directory
from vela.settings import DATA_DIR, region_by_id, settings
from vela.tables import compact_shards, pass_shard_name, write_pass_shard
from vela.train import (
    CANDIDATE_FILES,
    MODEL_ORDER,
    _prepare,
    candidate_identifiers,
    score_frozen_pipelines,
    selection_frame,
)

PLANNED_BYTES = 4_915_943_252
BUDGET_BYTES = 5_000_000_000
SELECTION = DATA_DIR / "models" / "model_selection.json"
CHECKPOINT = DATA_DIR / "catalog" / "validation_batch_checkpoint.json"
RESULTS = DATA_DIR / "models" / "preliminary_validation.json"
SELECTED_WEEKS = (
    {"region_id": "cerrado", "week_start": "2021-02-22", "week_end": "2021-02-28"},
    {"region_id": "california", "week_start": "2021-03-22", "week_end": "2021-03-28"},
    {"region_id": "zambia", "week_start": "2021-07-19", "week_end": "2021-07-25"},
)


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _verify_frozen_hashes() -> dict:
    saved = json.loads(SELECTION.read_text(encoding="utf-8"))
    current = candidate_identifiers()
    for name, item in saved["candidate_identifiers"].items():
        if current[name]["sha256"] != item["sha256"]:
            raise RuntimeError(f"Frozen hash mismatch for {name}.")
        print(f"Frozen {name} {item['sha256']}", flush=True)
    return saved


def _load_pipelines() -> dict:
    folder = DATA_DIR / "models"
    pipelines = {"raw_viirs": None}
    for name in ("logistic_regression", "random_forest"):
        pipelines[name] = joblib.load(folder / CANDIDATE_FILES[name])["pipeline"]
    return pipelines


def _week_rows(region_id: str, start: str, end: str) -> pd.DataFrame:
    table = DATA_DIR / "processed" / "paired_cells.parquet"
    frame = pd.read_parquet(table)
    prepared = _prepare(frame, settings())
    tune = selection_frame(prepared)
    dates = tune["local_date"]
    return tune[
        (tune["region_id"] == region_id)
        & (dates >= pd.Timestamp(start))
        & (dates <= pd.Timestamp(end))
    ].copy()


def _print_row(row: dict) -> None:
    if not row["scored"]:
        print(
            f"{row['region_id']} {row['dates']} days={row['usable_days']} "
            f"cells={row['eligible_cell_days']} unscored: {row['reason']}",
            flush=True,
        )
        return
    errors = row["absolute_error_percentage_points"]
    print(
        f"{row['region_id']} {row['dates']} days={row['usable_days']} "
        f"cells={row['eligible_cell_days']} "
        f"modis={row['observed_modis_rate']:.6f} "
        f"viirs={row['raw_viirs_rate']:.6f} "
        f"logistic={row['logistic_estimate']:.6f} "
        f"forest={row['random_forest_estimate']:.6f} "
        f"err_viirs={errors['raw_viirs']:.4f} "
        f"err_logistic={errors['logistic_regression']:.4f} "
        f"err_forest={errors['random_forest']:.4f}",
        flush=True,
    )


def _score_week(region_id: str, start: str, end: str, pipelines: dict, trained: list[str]) -> dict:
    part = _week_rows(region_id, start, end)
    cfg = settings()
    if part.empty:
        summary = summarize_week([], cfg)
        row = {
            "region_id": region_id,
            "region_group": "previously_trained" if region_id in set(trained) else "new",
            "dates": f"{start} to {end}",
            "eligible_dates": [],
            "usable_days": 0,
            "eligible_cell_days": 0,
            "coverage_status": "insufficient",
            "scored": False,
            "reason": insufficient_reason(summary, cfg),
            "observed_modis_rate": None,
            "raw_viirs_rate": None,
            "logistic_estimate": None,
            "random_forest_estimate": None,
            "absolute_error_percentage_points": {name: None for name in MODEL_ORDER},
        }
        return row
    scored = score_frozen_pipelines(part, pipelines, trained, cfg)
    if len(scored["weeks"]) != 1:
        raise RuntimeError(f"{region_id} {start} produced {len(scored['weeks'])} week rows.")
    week = scored["weeks"][0]
    dates = sorted(set(part["local_date"].dt.strftime("%Y-%m-%d")))
    summary = summarize_week(part.to_dict("records"), cfg)
    estimates = week["estimates"]
    row = {
        "region_id": region_id,
        "region_group": week["region_group"],
        "dates": ", ".join(dates),
        "eligible_dates": dates,
        "usable_days": week["usable_days"],
        "eligible_cell_days": week["usable_cell_days"],
        "coverage_status": week["coverage_status"],
        "scored": week["scored"],
        "reason": None if week["scored"] else insufficient_reason(summary, cfg),
        "observed_modis_rate": week["observed_modis_rate"],
        "raw_viirs_rate": None if estimates["raw_viirs"] is None else estimates["raw_viirs"],
        "logistic_estimate": estimates["logistic_regression"],
        "random_forest_estimate": estimates["random_forest"],
        "absolute_error_percentage_points": week["absolute_error_percentage_points"],
    }
    if int(part["iso_year"].min()) < 2021 or int(part["iso_year"].max()) > 2022:
        raise RuntimeError("A reserved year entered the validation score.")
    if "pantanal" in set(part["region_id"]) or "yakutia" in set(part["region_id"]):
        raise RuntimeError("A reserved region entered the validation score.")
    return row


def _results(rows: list[dict], transferred: int, hashes: dict) -> dict:
    scored = [row for row in rows if row["scored"]]
    def _count(group: str) -> int:
        return sum(1 for row in scored if row["region_group"] == group)

    return {
        "label": "preliminary validation",
        "selection_status": "pending",
        "minimum_scored_weeks": 4,
        "chosen_model": None,
        "final_test_evaluated": False,
        "reserved_not_run": ["yakutia", "2023-2024", "pantanal"],
        "planned_matched_pass_bytes": PLANNED_BYTES,
        "budget_bytes": BUDGET_BYTES,
        "bytes_transferred": transferred,
        "candidate_identifiers": hashes,
        "models_refit": False,
        "weeks": rows,
        "scored_weeks": len(scored),
        "scored_previously_trained_weeks": _count("previously_trained"),
        "scored_new_region_weeks": _count("new"),
    }


def main() -> int:
    saved = _verify_frozen_hashes()
    hashes = saved["candidate_identifiers"]
    pipelines = _load_pipelines()
    trained = list(hashes["logistic_regression"]["training_regions"])
    cfg = settings()
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8")) if CHECKPOINT.is_file() else {
        "completed": [],
        "bytes_downloaded": 0,
        "files": [],
        "week_rows": [],
    }
    completed = set(checkpoint["completed"])
    accounted = set(checkpoint.get("files") or [])
    for week in SELECTED_WEEKS:
        if week["region_id"] in {"yakutia", "pantanal"} or not week["week_start"].startswith(("2021", "2022")):
            raise RuntimeError("The batch list includes a reserved region or year.")
        region = region_by_id(week["region_id"])
        report, objects = discover_week(region, week["week_start"], week["week_end"], cfg)
        sizes = {}
        for name, granule in objects.items():
            sizes[name] = describe_granule(granule).get("size_bytes")
        print(
            f"{week['region_id']} {week['week_start']}: {report['candidate_count']} matched passes",
            flush=True,
        )
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
            extra = 0
            for name in missing:
                if name in accounted:
                    continue
                size = sizes.get(name)
                if size is None:
                    print(f"  missing a file size for {name}; download stopped", flush=True)
                    _save(CHECKPOINT, checkpoint)
                    return 2
                extra += int(size)
            if int(checkpoint["bytes_downloaded"]) + extra > BUDGET_BYTES:
                print("  next pass would exceed the 5 GB budget; download stopped", flush=True)
                _save(CHECKPOINT, checkpoint)
                return 2
            if missing:
                destination = DATA_DIR / "raw" / region["id"] / candidate["modis_time"][:10]
                print(f"  downloading {len(missing)} files for {candidate['modis_fire']}", flush=True)
                before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
                saved_paths = _download(objects, missing, destination)
                new_bytes = sum(
                    path.stat().st_size
                    for path in (Path(item) for item in saved_paths)
                    if path.resolve() not in before
                )
                checkpoint["bytes_downloaded"] = int(checkpoint.get("bytes_downloaded", 0)) + new_bytes
                accounted.update(missing)
                checkpoint["files"] = sorted(accounted)
                _save(CHECKPOINT, checkpoint)
                index = _index_raw()
            resolved = [_resolve(name, index) for name in names]
            if any(item is None for item in resolved):
                print(f"Missing a file for {candidate['modis_fire']}")
                return 2
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
            completed.add(stamp)
            checkpoint["completed"] = sorted(completed)
            _save(CHECKPOINT, checkpoint)
            print(
                f"  {stamp} eligible {len(processed['eligible'])} transferred {checkpoint['bytes_downloaded']}",
                flush=True,
            )
        row = _score_week(week["region_id"], week["week_start"], week["week_end"], pipelines, trained)
        _print_row(row)
        checkpoint["week_rows"] = [item for item in checkpoint.get("week_rows", []) if item["region_id"] != week["region_id"]]
        checkpoint["week_rows"].append(row)
        _save(CHECKPOINT, checkpoint)
        _save(RESULTS, _results(checkpoint["week_rows"], int(checkpoint["bytes_downloaded"]), hashes))
    _verify_frozen_hashes()
    if _fingerprint(DATA_DIR / "models" / CANDIDATE_FILES["logistic_regression"]) != hashes["logistic_regression"]["sha256"]:
        raise RuntimeError("Logistic candidate changed.")
    payload = _results(checkpoint.get("week_rows", []), int(checkpoint["bytes_downloaded"]), hashes)
    _save(RESULTS, payload)
    print(f"Transferred bytes: {payload['bytes_transferred']}", flush=True)
    print(f"Scored previously trained weeks: {payload['scored_previously_trained_weeks']}", flush=True)
    print(f"Scored new-region weeks: {payload['scored_new_region_weeks']}", flush=True)
    print("Candidate selection: pending", flush=True)
    print(f"Results: {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
