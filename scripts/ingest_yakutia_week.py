"""Download and score the preselected Yakutia week of 22–28 November 2021.

This retrieves the 14 matched Aqua and Suomi-NPP passes only. It does not
download NOAA-20, refit a candidate, or open the 2023–2024 final test or Pantanal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from scripts.ingest_validation_batch import (
    RESULTS,
    SELECTION,
    _load_pipelines,
    _print_row,
    _save,
    _verify_frozen_hashes,
)
from scripts.process_matched_passes import _four, _index_raw, _resolve
from scripts.smoke_test import _download
from vela.calendar_metrics import insufficient_reason, summarize_week
from vela.discover import discover_week
from vela.pipeline import describe_granule, process_directory
from vela.settings import DATA_DIR, region_by_id, settings
from vela.tables import compact_shards, pass_shard_name, write_pass_shard
from vela.train import MODEL_ORDER, _prepare, score_frozen_pipelines, selection_frame

WEEK = {"region_id": "yakutia", "week_start": "2021-11-22", "week_end": "2021-11-28"}
CHECKPOINT = DATA_DIR / "catalog" / "yakutia_week_checkpoint.json"
PROTOCOL = (
    ("cerrado", "2021-02-22"),
    ("california", "2021-03-22"),
    ("zambia", "2021-07-19"),
    ("yakutia", "2021-11-22"),
)
MAGIC = {
    ".hdf": b"\x0e\x03\x13\x01",
    ".nc": b"\x89HDF\r\n\x1a\n",
    ".h5": b"\x89HDF\r\n\x1a\n",
    ".hdf5": b"\x89HDF\r\n\x1a\n",
}


def _checksums(granule) -> list[dict]:
    umm = granule["umm"] if isinstance(granule, dict) and "umm" in granule else granule.get("umm", {})
    found = []
    for item in umm.get("DataGranule", {}).get("ArchiveAndDistributionInformation", []):
        checksum = item.get("Checksum") or {}
        value = checksum.get("Value")
        if not value:
            continue
        found.append(
            {
                "algorithm": str(checksum.get("Algorithm") or ""),
                "value": str(value).lower(),
            }
        )
    return found


def _file_checksum(path: Path, algorithm: str) -> str | None:
    name = algorithm.lower().replace("-", "")
    if name not in {"md5", "sha256", "sha1"}:
        return None
    digest = hashlib.new("sha256" if name == "sha256" else name)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _magic_ok(path: Path) -> bool:
    expected = MAGIC.get(path.suffix.lower())
    if expected is None:
        return path.stat().st_size > 0
    with path.open("rb") as handle:
        return handle.read(len(expected)) == expected


def _verify_local(path: Path, described: dict, checksum_rows: list[dict]) -> dict:
    actual = path.stat().st_size
    catalog = described.get("size_bytes")
    result = {
        "name": path.name,
        "bytes": actual,
        "catalog_bytes": catalog,
        "magic_ok": _magic_ok(path),
        "checksum": "not_in_catalog",
    }
    if not result["magic_ok"] or actual <= 0:
        raise RuntimeError(f"Integrity check failed for {path.name}: empty or unreadable header.")
    for item in checksum_rows:
        digest = _file_checksum(path, item["algorithm"])
        if digest is None:
            result["checksum"] = f"unsupported:{item['algorithm']}"
            continue
        if digest != item["value"]:
            raise RuntimeError(f"Checksum mismatch for {path.name}.")
        result["checksum"] = item["algorithm"]
        break
    return result


def _score_protocol(pipelines: dict, trained: list[str]) -> dict:
    table = DATA_DIR / "processed" / "paired_cells.parquet"
    excluded_path = DATA_DIR / "processed" / "excluded_cells.parquet"
    frame = pd.read_parquet(table)
    prepared = _prepare(frame, settings())
    tune = selection_frame(prepared)
    scored = score_frozen_pipelines(prepared, pipelines, trained, settings())
    by_key = {(row["region_id"], row["week_start"]): row for row in scored["weeks"]}
    rows = []
    for region_id, start in PROTOCOL:
        match = by_key.get((region_id, start))
        if match is None:
            rows.append(
                {
                    "region_id": region_id,
                    "week_start": start,
                    "scored": False,
                    "reason": "No eligible cell-days. The rate is missing.",
                    "eligible_cell_days": 0,
                    "reference_positives": 0,
                    "reference_zeros": 0,
                    "absolute_error_percentage_points": {name: None for name in MODEL_ORDER},
                }
            )
            continue
        rows.append(match)
    yakutia = tune[(tune["region_id"] == "yakutia") & (tune["local_date"] >= pd.Timestamp(WEEK["week_start"])) & (tune["local_date"] <= pd.Timestamp(WEEK["week_end"]))]
    excluded_count = 0
    if excluded_path.is_file():
        excluded = pd.read_parquet(excluded_path, columns=["region_id", "local_date"])
        dates = pd.to_datetime(excluded["local_date"])
        excluded_count = int(
            (
                (excluded["region_id"] == "yakutia")
                & (dates >= pd.Timestamp(WEEK["week_start"]))
                & (dates <= pd.Timestamp(WEEK["week_end"]))
            ).sum()
        )
    positives = int(yakutia["modis_detected"].astype(bool).sum()) if len(yakutia) else 0
    dates = sorted(set(yakutia["local_date"].dt.strftime("%Y-%m-%d"))) if len(yakutia) else []
    summary = summarize_week(yakutia.to_dict("records"), settings()) if len(yakutia) else summarize_week([], settings())
    for row in rows:
        if row["region_id"] == "yakutia" and not row.get("scored"):
            row["reason"] = insufficient_reason(summary, settings())
    return {
        "rows": rows,
        "eligible_cell_days": int(len(yakutia)),
        "eligible_dates": dates,
        "reference_positives": positives,
        "reference_zeros": int(len(yakutia) - positives),
        "excluded_rows": excluded_count,
        "scored_protocol": [row for row in rows if row.get("scored")],
    }


def _publish(protocol: dict, transferred: int, hashes: dict, integrity: dict) -> None:
    saved_validation = json.loads(RESULTS.read_text(encoding="utf-8"))
    saved_selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    existing = {row["region_id"]: row for row in saved_validation["weeks"]}
    published = []
    for row in protocol["rows"]:
        if row["region_id"] == "yakutia":
            if not row.get("scored"):
                published.append(
                    {
                        "region_id": "yakutia",
                        "region_group": "previously_trained",
                        "dates": ", ".join(protocol["eligible_dates"]) or f"{WEEK['week_start']} to {WEEK['week_end']}",
                        "eligible_dates": protocol["eligible_dates"],
                        "usable_days": row.get("usable_days", 0),
                        "eligible_cell_days": protocol["eligible_cell_days"],
                        "reference_positives": protocol["reference_positives"],
                        "reference_zeros": protocol["reference_zeros"],
                        "excluded_rows": protocol["excluded_rows"],
                        "coverage_status": "insufficient",
                        "scored": False,
                        "reason": row.get("reason") or insufficient_reason(summarize_week([], settings()), settings()),
                        "observed_modis_rate": None,
                        "raw_viirs_rate": None,
                        "logistic_estimate": None,
                        "random_forest_estimate": None,
                        "absolute_error_percentage_points": {name: None for name in MODEL_ORDER},
                    }
                )
                continue
            estimates = row["estimates"]
            published.append(
                {
                    "region_id": "yakutia",
                    "region_group": row["region_group"],
                    "dates": ", ".join(protocol["eligible_dates"]),
                    "eligible_dates": protocol["eligible_dates"],
                    "usable_days": row["usable_days"],
                    "eligible_cell_days": row["usable_cell_days"],
                    "reference_positives": protocol["reference_positives"],
                    "reference_zeros": protocol["reference_zeros"],
                    "excluded_rows": protocol["excluded_rows"],
                    "coverage_status": row["coverage_status"],
                    "scored": True,
                    "reason": None,
                    "observed_modis_rate": row["observed_modis_rate"],
                    "raw_viirs_rate": estimates["raw_viirs"],
                    "logistic_estimate": estimates["logistic_regression"],
                    "random_forest_estimate": estimates["random_forest"],
                    "absolute_error_percentage_points": row["absolute_error_percentage_points"],
                    "week_start": row["week_start"],
                }
            )
            continue
        published.append(existing[row["region_id"]])
    scored = [row for row in published if row.get("scored")]
    enough = len(scored) >= 4 and all(row.get("scored") for row in published)
    mae = {name: None for name in MODEL_ORDER}
    chosen = None
    if enough:
        mae = {
            name: float(sum(row["absolute_error_percentage_points"][name] for row in scored) / len(scored))
            for name in MODEL_ORDER
        }
        chosen = sorted(MODEL_ORDER, key=lambda name: (mae[name], MODEL_ORDER.index(name)))[0]
    saved_validation["weeks"] = published
    saved_validation["scored_weeks"] = len(scored)
    saved_validation["selection_status"] = "selected" if enough else "pending"
    saved_validation["chosen_model"] = chosen
    saved_validation["models_refit"] = False
    saved_validation["reserved_not_run"] = ["2023-2024", "pantanal"]
    saved_validation["yakutia_transfer"] = {
        "bytes_transferred": transferred,
        "download_authorized": True,
        "noaa20_downloaded": False,
        "integrity": integrity,
    }
    saved_validation["candidate_identifiers"] = hashes
    _save(RESULTS, saved_validation)
    saved_selection["weeks"] = published
    saved_selection["scored_weeks"] = len(scored)
    saved_selection["enough_weeks_to_select"] = enough
    saved_selection["weekly_mae_percentage_points"] = mae
    saved_selection["chosen_model"] = chosen
    saved_selection["selection_status"] = "selected" if enough else "preliminary"
    saved_selection["final_test_evaluated"] = False
    saved_selection["reveal_performance"] = "pending_until_final_test"
    if enough:
        saved_selection["gaps"] = []
    else:
        saved_selection["gaps"] = [
            "Scored validation weeks: "
            f"{len(scored)}; at least 4 are required before a candidate is selected."
        ]
    saved_selection["candidate_identifiers"] = hashes
    _save(SELECTION, saved_selection)


def main() -> int:
    saved = _verify_frozen_hashes()
    hashes = saved["candidate_identifiers"]
    pipelines = _load_pipelines()
    trained = list(hashes["logistic_regression"]["training_regions"])
    cfg = settings()
    region = region_by_id(WEEK["region_id"])
    report, objects = discover_week(region, WEEK["week_start"], WEEK["week_end"], cfg)
    described = {name: describe_granule(granule) for name, granule in objects.items()}
    checksum_by_name = {name: _checksums(granule) for name, granule in objects.items()}
    print(
        f"yakutia {WEEK['week_start']}: {report['candidate_count']} matched passes, "
        f"{len(objects)} granules in the search",
        flush=True,
    )
    if report["candidate_count"] != 14:
        print(f"Expected 14 matched passes and found {report['candidate_count']}.", flush=True)
    checkpoint = json.loads(CHECKPOINT.read_text(encoding="utf-8")) if CHECKPOINT.is_file() else {
        "completed": [],
        "bytes_downloaded": 0,
        "reused_files": [],
        "verified": [],
    }
    completed = set(checkpoint["completed"])
    verified = {item["name"]: item for item in checkpoint.get("verified") or []}
    index = _index_raw()
    for candidate in report["candidate_daytime_passes"]:
        stamp = pass_shard_name(region["id"], candidate["modis_fire"])
        names = _four(candidate)
        missing = [name for name in names if _resolve(name, index) is None]
        destination = DATA_DIR / "raw" / region["id"] / str(candidate["modis_time"])[:10]
        if missing:
            print(f"  downloading {len(missing)} files for {candidate['modis_fire']}", flush=True)
            before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
            saved_paths = _download(objects, missing, destination)
            new_bytes = sum(
                path.stat().st_size
                for path in (Path(item) for item in saved_paths)
                if path.resolve() not in before
            )
            checkpoint["bytes_downloaded"] = int(checkpoint.get("bytes_downloaded", 0)) + new_bytes
            _save(CHECKPOINT, checkpoint)
            index = _index_raw()
        else:
            checkpoint.setdefault("reused_files", [])
            for name in names:
                if name not in checkpoint["reused_files"]:
                    checkpoint["reused_files"].append(name)
        resolved = [_resolve(name, index) for name in names]
        if any(item is None for item in resolved):
            print(f"Missing a file for {candidate['modis_fire']}", flush=True)
            _save(CHECKPOINT, checkpoint)
            return 2
        for name, path in zip(names, resolved):
            info = described.get(name) or described.get(Path(name).name) or {"size_bytes": None}
            checks = checksum_by_name.get(name) or checksum_by_name.get(Path(name).name) or []
            record = _verify_local(path, info, checks)
            verified[path.name] = record
            print(
                f"  verified {path.name} bytes={record['bytes']} checksum={record['checksum']}",
                flush=True,
            )
        if stamp not in completed and not (DATA_DIR / "processed" / "shards" / stamp).is_file():
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
            print(
                f"  {stamp} eligible {len(processed['eligible'])} excluded {len(processed['excluded'])}",
                flush=True,
            )
        else:
            print(f"  already checkpointed {stamp}", flush=True)
        completed.add(stamp)
        checkpoint["completed"] = sorted(completed)
        checkpoint["verified"] = list(verified.values())
        _save(CHECKPOINT, checkpoint)
    integrity = {
        "files_verified": len(verified),
        "magic_failures": [item["name"] for item in verified.values() if not item["magic_ok"]],
        "checksums_in_catalog": sorted({item["checksum"] for item in verified.values()}),
        "catalog_bytes": sum(int(item["catalog_bytes"]) for item in verified.values() if item["catalog_bytes"] is not None),
        "bytes_on_disk": sum(int(item["bytes"]) for item in verified.values()),
    }
    protocol = _score_protocol(pipelines, trained)
    yakutia_row = next(row for row in protocol["rows"] if row["region_id"] == "yakutia")
    if yakutia_row.get("scored"):
        _print_row(
            {
                "region_id": "yakutia",
                "dates": f"{WEEK['week_start']} to {WEEK['week_end']}",
                "usable_days": yakutia_row["usable_days"],
                "eligible_cell_days": yakutia_row["usable_cell_days"],
                "scored": True,
                "observed_modis_rate": yakutia_row["observed_modis_rate"],
                "raw_viirs_rate": yakutia_row["estimates"]["raw_viirs"],
                "logistic_estimate": yakutia_row["estimates"]["logistic_regression"],
                "random_forest_estimate": yakutia_row["estimates"]["random_forest"],
                "absolute_error_percentage_points": yakutia_row["absolute_error_percentage_points"],
            }
        )
    else:
        print(f"yakutia unscored: {yakutia_row.get('reason')}", flush=True)
    print(
        f"eligible {protocol['eligible_cell_days']} positives {protocol['reference_positives']} "
        f"zeros {protocol['reference_zeros']} excluded {protocol['excluded_rows']}",
        flush=True,
    )
    _publish(protocol, int(checkpoint["bytes_downloaded"]), hashes, integrity)
    _verify_frozen_hashes()
    print(f"Transferred bytes: {checkpoint['bytes_downloaded']}", flush=True)
    print(f"Reused files: {len(checkpoint.get('reused_files') or [])}", flush=True)
    print(f"Files verified: {integrity['files_verified']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
