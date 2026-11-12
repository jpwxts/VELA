"""Download and grid the catalog's remaining daytime pairs, one pass at a time."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.messages import EARTHDATA_STEPS
from scripts.smoke_test import _download
from vela.discover import discover_week
from vela.pipeline import process_directory
from vela.settings import DATA_DIR, data_dir, region_by_id, settings
from vela.storage import StorageMeter
from vela.tables import compact_shards, pass_shard_name, write_pass_shard


def _index_raw() -> dict[str, Path]:
    index = {}
    root = DATA_DIR / "raw"
    if not root.exists():
        return index
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".hdf", ".nc", ".h5", ".hdf5"}:
            index[path.name] = path
            index.setdefault(path.stem, path)
    return index


def _resolve(name: str, index: dict[str, Path]) -> Path | None:
    return index.get(name) or index.get(Path(name).stem)


def _four(candidate: dict) -> list[str]:
    return [
        candidate["modis_fire"],
        candidate["modis_geo"],
        candidate["viirs_fire"],
        candidate["viirs_geo"],
    ]


def _retire_legacy_shards() -> None:
    folder = DATA_DIR / "processed" / "shards"
    if not folder.exists():
        return
    for path in list(folder.glob("*.parquet")):
        if path.stem.count("_") >= 2 and path.stem.rsplit("_", 2)[-2].isdigit():
            continue
        frame = pd.read_parquet(path, columns=["region_id", "modis_file"])
        names = frame["modis_file"].dropna().astype(str).unique()
        if len(names) != 1:
            continue
        target = folder / pass_shard_name(str(frame["region_id"].iloc[0]), names[0])
        if target.exists():
            path.unlink()
        else:
            path.rename(target)


def _additional_bytes(candidates: list[dict], index: dict[str, Path]) -> dict:
    pending = []
    additional = 0
    for candidate in candidates:
        names = _four(candidate)
        present = {name: _resolve(name, index) for name in names}
        missing = [name for name, path in present.items() if path is None]
        on_disk = sum(path.stat().st_size for path in present.values() if path is not None)
        catalog_bytes = candidate.get("bytes")
        if not missing:
            extra = 0
        elif catalog_bytes is None:
            extra = None
        else:
            extra = max(int(catalog_bytes) - on_disk, 0)
        if extra:
            additional += extra
        pending.append(
            {
                "modis_fire": candidate["modis_fire"],
                "modis_time": candidate["modis_time"],
                "bytes": catalog_bytes,
                "bytes_already_on_disk": on_disk,
                "additional_bytes": extra,
                "missing_files": missing,
            }
        )
    return {"additional_bytes": additional, "passes": pending}


def _summary(frame: pd.DataFrame, excluded: pd.DataFrame | None = None) -> dict:
    counts = (
        frame.groupby(["local_date", "outcome"], dropna=False)
        .size()
        .reset_index(name="cells")
        .sort_values(["local_date", "outcome"])
    )
    by_date = []
    for day, group in counts.groupby("local_date"):
        outcomes = {str(row.outcome): int(row.cells) for row in group.itertuples()}
        by_date.append(
            {
                "local_date": str(day),
                "outcomes": outcomes,
                "eligible": int(sum(outcomes.values())),
                "modis_positive": int(outcomes.get("both", 0) + outcomes.get("modis_only", 0)),
            }
        )
    seen = {item["local_date"] for item in by_date}
    if excluded is not None and len(excluded):
        for day, group in excluded.groupby(excluded["local_date"].astype(str)):
            if day in seen:
                continue
            reasons = {str(key): int(value) for key, value in group["exclusion_reason"].value_counts().items()}
            by_date.append(
                {
                    "local_date": str(day),
                    "outcomes": {},
                    "eligible": 0,
                    "modis_positive": 0,
                    "excluded": reasons,
                }
            )
    by_date.sort(key=lambda item: item["local_date"])
    positive = int(frame["modis_detected"].fillna(False).astype(bool).sum())
    observed = [item["local_date"] for item in by_date]
    return {
        "dataset": "pilot",
        "region_id": "cerrado",
        "eligible_cells": int(len(frame)),
        "distinct_dates": len(observed),
        "distinct_dates_with_eligible_cells": int(frame["local_date"].nunique()),
        "dates": observed,
        "modis_positive_examples": positive,
        "by_date": by_date,
        "model_selection": "not run",
        "reserved_region": "pantanal",
    }


def main() -> int:
    catalog_path = DATA_DIR / "catalog" / "search_report.json"
    report = json.loads(catalog_path.read_text(encoding="utf-8"))
    candidates = report.get("candidate_daytime_passes") or []
    if not candidates:
        print(f"{catalog_path} has no candidate daytime passes.")
        return 2
    _retire_legacy_shards()
    index = _index_raw()
    plan = _additional_bytes(candidates, index)
    data_dir("catalog").joinpath("remaining_passes.json").write_text(
        json.dumps(plan, indent=2),
        encoding="utf-8",
    )
    print(
        f"Additional download after excluding files already on disk: "
        f"{plan['additional_bytes']} bytes across {len(candidates)} catalog passes."
    )
    for item in plan["passes"]:
        print(
            f"  {item['modis_time'][:10]} {item['modis_fire']}: "
            f"additional {item['additional_bytes']} bytes, missing {len(item['missing_files'])}"
        )
    region = region_by_id(report["region_id"])
    cfg = settings()
    bbox = (region["west"], region["south"], region["east"], region["north"])
    objects = {}
    needs_download = any(item["missing_files"] for item in plan["passes"])
    if needs_download:
        fresh, objects = discover_week(region, report["start"], report["end"], cfg)
        if not fresh["earthdata_login"]:
            print(EARTHDATA_STEPS)
            return 2
    meter = StorageMeter(DATA_DIR)
    for number, candidate in enumerate(candidates, start=1):
        index = _index_raw()
        names = _four(candidate)
        missing = [name for name in names if _resolve(name, index) is None]
        stamp = pass_shard_name(region["id"], candidate["modis_fire"])
        shard = DATA_DIR / "processed" / "shards" / stamp
        if shard.is_file() and not missing:
            print(f"Pass {number}/{len(candidates)} already processed: {stamp}")
            continue
        if missing:
            unknown = [name for name in missing if name not in objects]
            if unknown:
                print(f"Catalog names were not in the earthaccess results: {unknown}")
                return 2
            destination = DATA_DIR / "raw" / region["id"] / candidate["modis_time"][:10]
            print(f"Pass {number}/{len(candidates)} downloading {len(missing)} files into {destination}")
            saved = _download(objects, missing, destination)
            for path in saved:
                meter.add_download(path.stat().st_size)
            index = _index_raw()
        paths = []
        for name in names:
            found = _resolve(name, index)
            if found is None:
                print(f"Missing {name} after download.")
                return 2
            paths.append(str(found))
        print(f"Pass {number}/{len(candidates)} reading {candidate['modis_fire']}")
        processed = process_directory(paths, bbox, region, cfg)
        rows = processed["eligible"] + processed["excluded"]
        if rows:
            write_pass_shard(rows, region["id"], candidate["modis_fire"])
            compact = compact_shards()
            print(
                f"Pass {number}/{len(candidates)} outcomes {processed['outcome_counts']}; "
                f"table now {compact['eligible']} eligible cell-days"
            )
        else:
            print(f"Pass {number}/{len(candidates)} produced no cells: {processed['granule_skips']}")
    compact_shards()
    table = DATA_DIR / "processed" / "paired_cells.parquet"
    excluded_path = DATA_DIR / "processed" / "excluded_cells.parquet"
    excluded = pd.read_parquet(excluded_path) if excluded_path.is_file() else None
    summary = _summary(pd.read_parquet(table), excluded)
    ledger_path = data_dir("metrics") / "download_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
    downloaded = int(ledger.get("bytes_downloaded", 0)) + meter.downloaded
    ledger_path.write_text(json.dumps({"bytes_downloaded": downloaded}, indent=2), encoding="utf-8")
    storage = meter.report()
    storage["bytes_downloaded"] = downloaded
    storage["bytes_downloaded_this_run"] = meter.downloaded
    summary["storage"] = storage
    summary["additional_download_bytes"] = plan["additional_bytes"]
    out = data_dir("processed") / "pilot_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"Pilot dates: {summary['distinct_dates']} observed, "
        f"{summary['distinct_dates_with_eligible_cells']} with eligible cells. "
        f"MODIS-positive examples: {summary['modis_positive_examples']}. "
        f"Eligible cells: {summary['eligible_cells']}."
    )
    for day in summary["by_date"]:
        if day["eligible"]:
            print(f"  {day['local_date']}: {day['outcomes']}")
        else:
            print(f"  {day['local_date']}: no eligible cells; excluded {day.get('excluded', {})}")
    print("Model selection was not run. Pantanal stays reserved.")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
