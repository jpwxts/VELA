"""Retrieve missing Aqua files and complete the Cerrado NOAA-20 transfer pilot.

Does nothing until --i-authorize-download is passed. Reuses the 20 verified
NOAA-20 files and any cached Aqua. Does not activate NOAA calibration, change
the Suomi-NPP model, or open held-out data.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from scripts.audit_noaa20_cerrado_aqua import (
    AUDIT_PATH,
    CALIFORNIA_INV,
    ORIGINAL_RESULT,
    PILOT_PATH,
    WEEK_ORDER,
    _audit_noaa_passes,
    _california_inventory,
    _complete_aqua_from_catalog,
    _record_week_order,
    _save,
    _search_aqua,
)
from scripts.process_matched_passes import _index_raw, _resolve
from scripts.smoke_test import _download
from vela.features import FEATURE_COLUMNS
from vela.pipeline import describe_granule, process_directory, search_product, try_login
from vela.settings import DATA_DIR, region_by_id, settings
from vela.train import _prepare

DEFAULT_MANIFEST = DATA_DIR / "catalog" / "noaa20_cerrado_missing_aqua_manifest.json"
COMPLETED_RESULT = DATA_DIR / "models" / "noaa20_cerrado_transfer_pilot_archive_completed.json"
PRESERVED_ORIGINAL = DATA_DIR / "models" / "noaa20_cerrado_transfer_pilot_cache_limited_original.json"
PILOT_TABLE = DATA_DIR / "processed" / "noaa20_cerrado_pilot_cells_archive_completed.parquet"
CHECKPOINT = DATA_DIR / "catalog" / "noaa20_cerrado_aqua_download_checkpoint.json"


def _download_missing(manifest: dict) -> dict:
    names = list(manifest.get("missing_file_names") or [])
    region = region_by_id("cerrado")
    bbox = (region["west"], region["south"], region["east"], region["north"])
    cfg = settings()
    objects = {}
    for key in ("MYD14", "MYD03"):
        product = cfg["products"][key]
        results, _version, _error = search_product(
            product["short_name"], product["version"], bbox, "2021-02-22", "2021-02-28"
        )
        for granule in results or []:
            info = describe_granule(granule)
            if info.get("name"):
                objects[info["name"]] = granule
                objects[Path(info["name"]).stem] = granule
    index = _index_raw()
    missing = []
    for name in names:
        if _resolve(name, index) is None and _resolve(f"{Path(name).stem}.hdf", index) is None:
            missing.append(name)
    unresolved = [name for name in missing if name not in objects and Path(name).stem not in objects]
    if unresolved:
        raise RuntimeError(f"Catalog names were not in the earthaccess results: {unresolved}")
    checkpoint = {
        "bytes_downloaded": 0,
        "verification": [],
        "already_cached_before_download": [name for name in names if name not in missing],
        "requested": names,
    }
    if not missing:
        print("All listed Aqua files are already cached.")
        _save(CHECKPOINT, checkpoint)
        return checkpoint
    destination = DATA_DIR / "raw" / "cerrado" / "aqua_for_noaa20_pilot"
    print(f"Downloading {len(missing)} Aqua files into {destination}", flush=True)
    before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
    saved = _download(objects, missing, destination)
    transferred = 0
    for path in saved:
        size = path.stat().st_size
        if path.resolve() not in before:
            transferred += size
        checkpoint["verification"].append(
            {
                "name": path.name,
                "bytes": size,
                "exists": path.is_file(),
                "suffix": path.suffix.lower(),
                "path": str(path),
            }
        )
    checkpoint["bytes_downloaded"] = int(transferred)
    # Verify every requested name resolves after download.
    index = _index_raw()
    resolved = []
    for name in names:
        path = _resolve(name, index) or _resolve(f"{Path(name).stem}.hdf", index)
        resolved.append(
            {
                "name": name,
                "resolved": path is not None,
                "bytes": None if path is None else path.stat().st_size,
                "path": None if path is None else str(path),
            }
        )
    checkpoint["resolved_after_download"] = resolved
    checkpoint["all_resolved"] = all(item["resolved"] for item in resolved)
    _save(CHECKPOINT, checkpoint)
    print(f"Transferred bytes: {checkpoint['bytes_downloaded']}", flush=True)
    return checkpoint


def _score_and_reconcile(accepted_rows: list[dict], pilot: dict, region: dict, download: dict) -> dict:
    """Process each NOAA-20 candidate against its best Aqua (NOAA-centric).

    Aqua-centric pairing would drop a second NOAA-20 granule that shares one Aqua
    stamp (as on 24 Feb). Transfer scoring keeps both coverages, then choose_one
    enforces one NOAA-20 contribution per cell-date.
    """

    import gc

    from vela.harmonize import aggregate, choose_one, exclusion_summary, rows_for_pair, split_kept
    from vela.pairing import parse_granule_name
    from vela.readers import read_pass

    index = _index_raw()
    bbox = (region["west"], region["south"], region["east"], region["north"])
    cfg = settings()

    def resolve(name: str) -> Path:
        path = (
            _resolve(name, index)
            or _resolve(f"{Path(name).stem}.nc", index)
            or _resolve(f"{Path(name).stem}.hdf", index)
        )
        if path is None:
            raise RuntimeError(f"Required file missing after download: {name}")
        return path

    match_details = []
    pairs = []
    for row in accepted_rows:
        aqua_fire = resolve(row["best_candidate_aqua_fire"])
        aqua_geo = resolve(row["best_candidate_aqua_geolocation"])
        noaa_fire = resolve(row["noaa20_fire"])
        noaa_geo = resolve(row["noaa20_geolocation"])
        aqua_meta = parse_granule_name(aqua_fire)
        noaa_meta = parse_granule_name(noaa_fire)
        detail = {
            "noaa20_acquisition_time": row["noaa20_acquisition_time"],
            "noaa20_fire": row["noaa20_fire"],
            "aqua_time": row["best_candidate_aqua_time"],
            "aqua_stamp": row["best_candidate_aqua_stamp"],
            "delta_minutes": row["time_difference_minutes"],
            "paths": [str(aqua_fire), str(aqua_geo), str(noaa_fire), str(noaa_geo)],
        }
        match_details.append(detail)
        pairs.append(
            {
                "modis": {
                    "platform": "Aqua",
                    "stamp": aqua_meta["stamp"],
                    "when": aqua_meta["when"],
                    "fire": str(aqua_fire),
                    "geo": str(aqua_geo),
                    "fire_name": aqua_fire.name,
                    "geo_name": aqua_geo.name,
                },
                "viirs": {
                    "platform": "NOAA-20",
                    "stamp": noaa_meta["stamp"],
                    "when": noaa_meta["when"],
                    "fire": str(noaa_fire),
                    "geo": str(noaa_geo),
                    "fire_name": noaa_fire.name,
                    "geo_name": noaa_geo.name,
                },
                "delta_minutes": row["time_difference_minutes"],
                "noaa20_acquisition_time": row["noaa20_acquisition_time"],
            }
        )

    print(f"Processing {len(pairs)} NOAA-20-centric candidate matches", flush=True)
    collected = []
    confirmed = []
    granule_skips = []
    match_coverage = []
    for pair in pairs:
        modis_read = read_pass(pair["modis"]["fire"], pair["modis"]["geo"], bbox, pair["modis"]["when"], cfg)
        if not modis_read["ok"]:
            granule_skips.append({"stamp": pair["modis"]["stamp"], "platform": "Aqua", "reason": modis_read["reason"]})
            match_coverage.append(
                {
                    "noaa20_acquisition_time": pair["noaa20_acquisition_time"],
                    "noaa20_fire": pair["viirs"]["fire_name"],
                    "status": "aqua_read_failed",
                    "rows": 0,
                    "eligible_before_choose_one": 0,
                    "eligible_after_choose_one": 0,
                    "has_eligible_cells": False,
                }
            )
            continue
        viirs_read = read_pass(pair["viirs"]["fire"], pair["viirs"]["geo"], bbox, pair["viirs"]["when"], cfg)
        if not viirs_read["ok"]:
            granule_skips.append({"stamp": pair["viirs"]["stamp"], "platform": "NOAA-20", "reason": viirs_read["reason"]})
            match_coverage.append(
                {
                    "noaa20_acquisition_time": pair["noaa20_acquisition_time"],
                    "noaa20_fire": pair["viirs"]["fire_name"],
                    "status": "noaa_read_failed",
                    "rows": 0,
                    "eligible_before_choose_one": 0,
                    "eligible_after_choose_one": 0,
                    "has_eligible_cells": False,
                }
            )
            del modis_read
            gc.collect()
            continue
        modis_cells = aggregate(modis_read["lon"], modis_read["lat"], modis_read["classes"], "modis")
        viirs_cells = aggregate(viirs_read["lon"], viirs_read["lat"], viirs_read["classes"], "viirs")
        if not (set(modis_cells) & set(viirs_cells)):
            granule_skips.append({"stamp": pair["modis"]["stamp"], "platform": "both", "reason": "no_overlapping_land"})
            match_coverage.append(
                {
                    "noaa20_acquisition_time": pair["noaa20_acquisition_time"],
                    "noaa20_fire": pair["viirs"]["fire_name"],
                    "status": "no_overlapping_land",
                    "rows": 0,
                    "eligible_before_choose_one": 0,
                    "eligible_after_choose_one": 0,
                    "has_eligible_cells": False,
                }
            )
        else:
            meta = {
                "region_id": region["id"],
                "region_name": region.get("name", region["id"]),
                "landscape": region.get("landscape", ""),
                "role": region.get("role", "unspecified"),
                "modis_file": pair["modis"]["fire_name"],
                "viirs_file": pair["viirs"]["fire_name"],
                "modis_geo_file": pair["modis"]["geo_name"],
                "viirs_geo_file": pair["viirs"]["geo_name"],
                "modis_time": pair["modis"]["when"],
                "viirs_time": pair["viirs"]["when"],
                "viirs_platform": "NOAA-20",
            }
            rows = rows_for_pair(modis_cells, viirs_cells, meta, cfg)
            eligible_before = sum(1 for item in rows if item.get("eligible"))
            collected.extend(rows)
            confirmed.append(
                {
                    "modis_file": pair["modis"]["fire_name"],
                    "viirs_file": pair["viirs"]["fire_name"],
                    "viirs_platform": "NOAA-20",
                    "delta_minutes": pair["delta_minutes"],
                    "rows": len(rows),
                    "eligible_before_choose_one": eligible_before,
                    "noaa20_acquisition_time": pair["noaa20_acquisition_time"],
                }
            )
            match_coverage.append(
                {
                    "noaa20_acquisition_time": pair["noaa20_acquisition_time"],
                    "noaa20_fire": pair["viirs"]["fire_name"],
                    "aqua_stamp": pair["modis"]["stamp"],
                    "delta_minutes": pair["delta_minutes"],
                    "status": "processed",
                    "rows": len(rows),
                    "eligible_before_choose_one": eligible_before,
                }
            )
        del modis_read, viirs_read, modis_cells, viirs_cells
        gc.collect()

    kept, duplicates = choose_one(collected)
    eligible_rows, excluded = split_kept(kept)
    excluded.extend(duplicates)
    all_rows = eligible_rows + excluded
    if all_rows:
        pd.DataFrame(all_rows).to_parquet(PILOT_TABLE, index=False)

    eligible = [
        row
        for row in eligible_rows
        if row.get("outcome") == "eligible" and str(row.get("viirs_platform") or "") == "NOAA-20"
    ]
    for item in match_coverage:
        stem = Path(str(item.get("noaa20_fire") or "")).stem
        after = [row for row in eligible if Path(str(row.get("viirs_file") or "")).stem == stem]
        item["eligible_after_choose_one"] = len(after)
        item["has_eligible_cells"] = bool(after)

    keys = [(row["cell_id"], str(row["local_date"])[:10]) for row in eligible]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Eligible NOAA-20 cell-days are not unique after choose_one.")

    if PRESERVED_ORIGINAL.is_file():
        original_path = str(PRESERVED_ORIGINAL)
    else:
        shutil.copy2(ORIGINAL_RESULT, PRESERVED_ORIGINAL)
        original_path = str(PRESERVED_ORIGINAL)
    original = json.loads(Path(original_path).read_text(encoding="utf-8"))

    result = {
        "label": "NOAA-20 transfer pilot archive-completed",
        "preserves_original_cache_limited_pilot": original_path,
        "original_result_file": str(ORIGINAL_RESULT),
        "operational_harmonized_estimate": "calibration pending",
        "research_status": "transfer pilot evaluated",
        "region_id": pilot["region_id"],
        "week_start": pilot["week_start"],
        "week_end": pilot["week_end"],
        "protocol_amendment": "2026-11-12b",
        "bytes_transferred": int(download.get("bytes_downloaded") or 0),
        "estimated_additional_bytes": 112_445_976,
        "verification": download.get("verification") or [],
        "resolved_after_download": download.get("resolved_after_download") or [],
        "all_requested_aqua_resolved": bool(download.get("all_resolved", True)),
        "pairing_mode": "noaa20_centric_best_aqua_within_30_min",
        "candidate_matches": len(accepted_rows),
        "candidate_match_details": match_details,
        "matches_with_any_collected_cells": sum(1 for item in match_coverage if (item.get("rows") or 0) > 0),
        "matches_with_eligible_cells": sum(1 for item in match_coverage if item.get("has_eligible_cells")),
        "match_coverage": match_coverage,
        "duplicate_cell_days_resolved": len(duplicates),
        "final_unique_eligible_cell_days": len(eligible),
        "confirmed_passes": confirmed,
        "exclusion_counts": exclusion_summary(excluded),
        "granule_skips": granule_skips,
        "calibration_activated": False,
        "selected_suomi_model": "random_forest",
        "selected_suomi_model_changed": False,
        "noaa21_status": "calibration pending",
        "final_test_evaluated": False,
        "pantanal_opened": False,
        "held_out_untouched": True,
        "native_detections_preserved": True,
        "predictions_path": str(PILOT_TABLE),
        "feb24_note": (
            "On 24 February, NOAA-20 16:24 and 16:30 both match Aqua 16:25. "
            "Both pairs were processed under NOAA-20-centric pairing; choose_one kept one NOAA-20 contribution per cell-date."
        ),
    }

    if not eligible:
        result.update(
            {
                "aqua_positives": 0,
                "aqua_zeros": 0,
                "observed_aqua_rate": None,
                "raw_noaa20_rate": None,
                "frozen_model_mean_probability": None,
                "signed_difference_percentage_points": {"raw_noaa20": None, "frozen_random_forest": None},
                "absolute_error_percentage_points": {"raw_noaa20": None, "frozen_random_forest": None},
                "errors_undefined": True,
                "coverage_lost_where": f"exclusion_counts={result['exclusion_counts']}",
                "reason": "Zero jointly eligible NOAA-20/Aqua cell-days after measured shared visible land.",
            }
        )
        _save(COMPLETED_RESULT, result)
        return result

    artifact = joblib.load(DATA_DIR / "models" / "vela_model.joblib")
    if artifact.get("model_name") != "random_forest":
        raise RuntimeError("Selected Suomi-NPP model drifted from random_forest.")
    frame = _prepare(pd.DataFrame(eligible), settings())
    probs = artifact["pipeline"].predict_proba(frame.loc[:, list(FEATURE_COLUMNS)])[:, 1]
    aqua = frame["modis_detected"].astype(float).to_numpy()
    raw = (frame["viirs_hotspot_pixels"].astype(float).to_numpy() >= 1.0).astype(float)
    aqua_rate = float(aqua.mean())
    raw_rate = float(raw.mean())
    model_rate = float(np.mean(probs))
    positives = int(aqua.sum())
    zeros = int(len(eligible) - positives)
    signed = {
        "raw_noaa20": (raw_rate - aqua_rate) * 100.0,
        "frozen_random_forest": (model_rate - aqua_rate) * 100.0,
    }
    absolute = {key: abs(value) for key, value in signed.items()}
    result.update(
        {
            "aqua_positives": positives,
            "aqua_zeros": zeros,
            "observed_aqua_rate": aqua_rate,
            "raw_noaa20_rate": raw_rate,
            "frozen_model_mean_probability": model_rate,
            "signed_difference_percentage_points": signed,
            "absolute_error_percentage_points": absolute,
            "errors_undefined": False,
            "frozen_model": original.get("frozen_model"),
            "low_activity_interpretation": (
                None
                if positives > 0
                else (
                    "Aqua recorded zero positives on the jointly eligible cell-days, so the measured Aqua "
                    "activity rate is 0%. This week tests transfer under low-activity / clear-zero conditions. "
                    "Active-fire transfer under high Aqua activity remains unknown."
                )
            ),
        }
    )
    _save(COMPLETED_RESULT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--i-authorize-download", action="store_true")
    args = parser.parse_args()
    if not args.i_authorize_download:
        print(
            "Download is not authorized. Re-run with --i-authorize-download after review. "
            f"Manifest: {args.manifest}"
        )
        return 2
    if not try_login():
        print("Earthdata login required.")
        return 2

    _record_week_order()
    if ORIGINAL_RESULT.is_file() and not PRESERVED_ORIGINAL.is_file():
        shutil.copy2(ORIGINAL_RESULT, PRESERVED_ORIGINAL)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    download = _download_missing(manifest)
    if download.get("resolved_after_download") and not download.get("all_resolved", True):
        print("Not all requested Aqua files resolved after download.")
        return 2

    pilot = json.loads(PILOT_PATH.read_text(encoding="utf-8"))
    region = region_by_id(pilot["region_id"])
    aqua_search = _search_aqua(region, pilot["week_start"], pilot["week_end"])
    aqua_ready, _incomplete = _complete_aqua_from_catalog(aqua_search["described"])
    rows = _audit_noaa_passes(pilot, aqua_ready, region, aqua_search["query_status"])
    accepted = [row for row in rows if row["decision"] == "accepted_catalog_pair"]
    # Refresh cache statuses after download.
    index = _index_raw()
    for row in accepted:
        fire = row.get("best_candidate_aqua_fire")
        geo = row.get("best_candidate_aqua_geolocation")
        fire_path = None if not fire else (_resolve(fire, index) or _resolve(f"{Path(fire).stem}.hdf", index))
        geo_path = None if not geo else (_resolve(geo, index) or _resolve(f"{Path(geo).stem}.hdf", index))
        row["fire_cached"] = fire_path is not None
        row["geo_cached"] = geo_path is not None
        row["cache_status"] = (
            "cached" if fire_path and geo_path else ("partially_cached" if fire_path or geo_path else "missing")
        )
    still_missing = [row for row in accepted if row["cache_status"] != "cached"]
    if still_missing:
        print(f"Accepted pairs still missing Aqua after download: {len(still_missing)}")
        return 2
    if len(accepted) != 5:
        print(f"Expected 5 accepted candidate matches; found {len(accepted)}")
        # Continue with whatever accepted catalog pairs are fully cached.
    result = _score_and_reconcile(accepted, pilot, region, download)

    # Update research labels without activating operational calibration.
    pilot.update(
        {
            "research_status": "transfer pilot evaluated",
            "harmonized_estimate": "calibration pending",
            "calibration_activated": False,
            "archive_completed_result": str(COMPLETED_RESULT),
            "bytes_transferred_aqua_completion": result["bytes_transferred"],
        }
    )
    _save(PILOT_PATH, pilot)

    print("Preparing California metadata-only inventory for the next recorded week", flush=True)
    california = _california_inventory()
    result["california_inventory"] = {
        "file": str(CALIFORNIA_INV),
        "candidate_pair_count": california.get("candidate_pair_count"),
        "estimated_additional_bytes": california.get("estimated_additional_bytes"),
        "download_authorized_this_run": False,
    }
    result["week_order"] = json.loads(WEEK_ORDER.read_text(encoding="utf-8"))
    _save(COMPLETED_RESULT, result)

    # Keep audit pointer current.
    if AUDIT_PATH.is_file():
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        audit["archive_completed_result"] = str(COMPLETED_RESULT)
        audit["california_inventory"] = str(CALIFORNIA_INV)
        _save(AUDIT_PATH, audit)

    print(
        json.dumps(
            {
                "bytes_transferred": result["bytes_transferred"],
                "candidate_matches": result["candidate_matches"],
                "matches_with_eligible_cells": result["matches_with_eligible_cells"],
                "duplicate_cell_days_resolved": result["duplicate_cell_days_resolved"],
                "final_unique_eligible_cell_days": result["final_unique_eligible_cell_days"],
                "aqua_positives": result.get("aqua_positives"),
                "aqua_zeros": result.get("aqua_zeros"),
                "observed_aqua_rate": result.get("observed_aqua_rate"),
                "raw_noaa20_rate": result.get("raw_noaa20_rate"),
                "frozen_model_mean_probability": result.get("frozen_model_mean_probability"),
                "signed_difference_percentage_points": result.get("signed_difference_percentage_points"),
                "absolute_error_percentage_points": result.get("absolute_error_percentage_points"),
                "errors_undefined": result.get("errors_undefined"),
                "calibration_activated": result["calibration_activated"],
                "california_additional_bytes": california.get("estimated_additional_bytes"),
                "california_candidate_pairs": california.get("candidate_pair_count"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
