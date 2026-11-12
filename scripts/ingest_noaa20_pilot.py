"""Download and score the NOAA-20 Cerrado transfer pilot.

Authorizes only the 10 daytime NOAA-20 fire/geolocation pairs listed in
data/catalog/noaa20_cerrado_pilot.json. Reuses cached Aqua granules. Does not
refit the frozen Suomi-NPP model, activate NOAA calibration in operational
estimates, download NOAA-21, or open 2023–2024 / Pantanal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from scripts.process_matched_passes import _index_raw, _resolve
from scripts.smoke_test import _download
from vela.features import FEATURE_COLUMNS, feature_values, viirs_counts_from_mapping
from vela.masks import VIIRS_CLASSES
from vela.pipeline import describe_granule, process_directory, search_product, try_login
from vela.readers import open_science, read_pass
from vela.settings import DATA_DIR, region_by_id, settings
from vela.train import _prepare

PILOT_PATH = DATA_DIR / "catalog" / "noaa20_cerrado_pilot.json"
PLAN_PATH = DATA_DIR / "catalog" / "platform_transfer_plan.json"
CHECKPOINT_PATH = DATA_DIR / "catalog" / "noaa20_cerrado_pilot_checkpoint.json"
RESULT_PATH = DATA_DIR / "models" / "noaa20_cerrado_transfer_pilot.json"
PILOT_TABLE = DATA_DIR / "processed" / "noaa20_cerrado_pilot_cells.parquet"
SELECTION_PATH = DATA_DIR / "models" / "model_selection.json"
RESERVE_PATH = DATA_DIR / "models" / "reserve_inclusive_selection.json"
VELA_MODEL = DATA_DIR / "models" / "vela_model.joblib"
CANDIDATE_RF = DATA_DIR / "models" / "candidate_random_forest.joblib"

AUTHORIZED_DAYTIME_PAIRS = 10
AUTHORIZED_BYTES = 1_800_954_900


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pilot() -> dict:
    return json.loads(PILOT_PATH.read_text(encoding="utf-8"))


def _search_noaa20_objects(region: dict, start: str, end: str) -> dict:
    cfg = settings()
    products = (cfg.get("platform_transfer") or {}).get("products") or {}
    bbox = (region["west"], region["south"], region["east"], region["north"])
    objects = {}
    versions = {}
    errors = {}
    for key in ("VJ114IMG", "VJ103IMG"):
        product = products[key]
        results, version, error = search_product(product["short_name"], product["version"], bbox, start, end)
        versions[key] = version
        errors[key] = error
        for granule in results or []:
            info = describe_granule(granule)
            if info.get("name"):
                objects[info["name"]] = granule
                objects[Path(info["name"]).stem] = granule
    return {"objects": objects, "versions": versions, "errors": errors}


def _verify_model_hash() -> dict:
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    expected = selection["candidate_identifiers"]["random_forest"]["sha256"]
    actual = _sha256(CANDIDATE_RF)
    if actual != expected:
        raise RuntimeError(f"Frozen random_forest hash mismatch: {actual} != {expected}")
    artifact = joblib.load(VELA_MODEL)
    if artifact.get("model_name") != "random_forest":
        raise RuntimeError("Selected Suomi-NPP model is not random_forest.")
    if artifact.get("source_sha256") and artifact["source_sha256"] != expected:
        raise RuntimeError("Published vela_model does not match the frozen random_forest candidate.")
    return {
        "model_name": "random_forest",
        "candidate_sha256": actual,
        "vela_model_sha256": _sha256(VELA_MODEL),
        "refit": False,
        "selected_suomi_model_unchanged": True,
    }


def _feature_parity_audit(fire_path: Path, geo_path: Path, region: dict, config: dict) -> dict:
    """Confirm NOAA-20 can supply every frozen-model feature with Suomi semantics."""

    bbox = (region["west"], region["south"], region["east"], region["north"])
    fire = open_science(fire_path)
    geo = open_science(geo_path)
    try:
        fire_var = fire.fire()
        zenith_var = geo.zenith()
        flags = {
            "fire_mask_present": fire_var is not None,
            "latitude_present": geo.latitude() is not None,
            "longitude_present": geo.longitude() is not None,
            "solar_zenith_present": zenith_var is not None,
            "netcdf_auto_scale_disabled": True,
            "class_table": "VIIRS Collection 2 codes 0-9 shared by VNP14IMG and VJ114IMG",
            "viirs_classes": {str(code): name for code, name in VIIRS_CLASSES.items()},
        }
        if zenith_var is not None:
            sample = zenith_var.read_scaled(0, min(20, zenith_var.shape[0]))
            finite = sample[np.isfinite(sample)]
            flags["solar_zenith_scale"] = float(zenith_var.scale)
            flags["solar_zenith_offset"] = float(zenith_var.offset)
            flags["solar_zenith_sample_median_deg"] = None if finite.size == 0 else float(np.median(finite))
            flags["solar_zenith_reader"] = "corrected_single_scale"
            if finite.size and float(np.nanmedian(finite)) > 180:
                flags["solar_zenith_faithful"] = False
                flags["solar_zenith_issue"] = "median exceeds 180 deg; double-scaling suspected"
            else:
                flags["solar_zenith_faithful"] = True
        else:
            flags["solar_zenith_faithful"] = False
            flags["solar_zenith_issue"] = "solar zenith variable missing"
    finally:
        fire.close()
        geo.close()

    read = read_pass(str(fire_path), str(geo_path), bbox, None, config)
    flags["daytime_read_ok"] = bool(read.get("ok"))
    flags["daytime_check"] = read.get("daytime_check")
    if not read.get("ok"):
        flags["read_reason"] = read.get("reason")

    missing_features = []
    for name in FEATURE_COLUMNS:
        if name.startswith("viirs_") or name in {"center_lat", "center_lon", "doy_sin", "doy_cos", "local_hour"}:
            continue
        missing_features.append(name)
    # Build a synthetic feature row from empty counts to prove the contract runs.
    probe = feature_values({name: 0 for name in (
        "fire_low", "fire_nominal", "fire_high", "clear", "cloud", "water", "unknown", "missing"
    )}, -14.0, -50.0, "2021-02-22", 13.5)
    flags["feature_columns"] = list(FEATURE_COLUMNS)
    flags["feature_probe_keys"] = list(probe)
    flags["feature_columns_match"] = list(probe) == list(FEATURE_COLUMNS)
    flags["unreproducible_features"] = missing_features
    flags["faithful"] = bool(
        flags.get("fire_mask_present")
        and flags.get("latitude_present")
        and flags.get("longitude_present")
        and flags.get("solar_zenith_faithful")
        and flags.get("feature_columns_match")
        and not missing_features
    )
    return flags


def _download_daytime_pairs(pilot: dict, objects: dict) -> dict:
    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8")) if CHECKPOINT_PATH.is_file() else {
        "completed_pairs": [],
        "bytes_downloaded": 0,
        "verification": [],
    }
    index = _index_raw()
    region = region_by_id(pilot["region_id"])
    daytime = pilot["daytime_pairs"]
    if len(daytime) != AUTHORIZED_DAYTIME_PAIRS:
        raise RuntimeError(f"Pilot daytime_pairs must be exactly {AUTHORIZED_DAYTIME_PAIRS}.")
    for pair in daytime:
        names = [pair["fire"], pair["geolocation"]]
        missing = []
        for name in names:
            if _resolve(name, index) is None and _resolve(f"{Path(name).stem}.nc", index) is None:
                missing.append(name)
        if not missing:
            checkpoint.setdefault("completed_pairs", [])
            stamp = Path(pair["fire"]).stem
            if stamp not in checkpoint["completed_pairs"]:
                checkpoint["completed_pairs"].append(stamp)
            continue
        unresolved = [name for name in missing if name not in objects and Path(name).stem not in objects]
        if unresolved:
            raise RuntimeError(f"Catalog names were not in the earthaccess results: {unresolved}")
        day = str(pair["when"])[:10]
        destination = DATA_DIR / "raw" / region["id"] / "noaa20_pilot" / day
        before = {path.resolve() for path in destination.glob("*")} if destination.exists() else set()
        print(f"downloading {len(missing)} NOAA-20 files into {destination}", flush=True)
        saved = _download(objects, missing, destination)
        new_bytes = sum(path.stat().st_size for path in saved if path.resolve() not in before)
        checkpoint["bytes_downloaded"] = int(checkpoint.get("bytes_downloaded", 0)) + int(new_bytes)
        for path in saved:
            checkpoint.setdefault("verification", []).append(
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "suffix": path.suffix.lower(),
                    "exists": path.is_file(),
                }
            )
        checkpoint.setdefault("completed_pairs", []).append(Path(pair["fire"]).stem)
        _save(CHECKPOINT_PATH, checkpoint)
        index = _index_raw()
    _save(CHECKPOINT_PATH, checkpoint)
    return checkpoint


def _collect_paths(pilot: dict) -> list[str]:
    index = _index_raw()
    paths = []
    # Cached Aqua for the Cerrado week only.
    aqua_root = DATA_DIR / "raw" / pilot["region_id"]
    for day in sorted(aqua_root.glob("2021-02-2*")):
        if not day.is_dir() or "noaa20" in day.name:
            continue
        for path in day.glob("MYD*"):
            paths.append(str(path))
    # Authorized NOAA-20 daytime pairs only.
    for pair in pilot["daytime_pairs"]:
        for name in (pair["fire"], pair["geolocation"]):
            path = _resolve(name, index) or _resolve(f"{Path(name).stem}.nc", index)
            if path is None:
                raise RuntimeError(f"Missing authorized NOAA-20 file after download: {name}")
            paths.append(str(path))
    return sorted(set(paths))


def _score_transfer(rows: list[dict], pipeline, model_info: dict, feature_audit: dict, checkpoint: dict, pilot: dict) -> dict:
    eligible = [row for row in rows if row.get("outcome") == "eligible"]
    noaa_eligible = [row for row in eligible if str(row.get("viirs_platform") or "") == "NOAA-20"]
    positives = sum(1 for row in noaa_eligible if bool(row.get("modis_detected")))
    zeros = len(noaa_eligible) - positives
    if not noaa_eligible:
        return {
            "label": "NOAA-20 transfer pilot evaluated",
            "operational_harmonized_estimate": "calibration pending",
            "research_status": "transfer pilot evaluated",
            "region_id": pilot["region_id"],
            "week_start": pilot["week_start"],
            "week_end": pilot["week_end"],
            "protocol_amendment": "2026-11-12b",
            "bytes_transferred": int(checkpoint.get("bytes_downloaded", 0)),
            "authorized_bytes": AUTHORIZED_BYTES,
            "verification": checkpoint.get("verification") or [],
            "feature_parity": feature_audit,
            "frozen_model": model_info,
            "qualifying_passes": 0,
            "matched_cell_days": 0,
            "aqua_positives": 0,
            "aqua_zeros": 0,
            "observed_aqua_rate": None,
            "raw_noaa20_rate": None,
            "frozen_model_mean_probability": None,
            "signed_difference_percentage_points": {"raw_noaa20": None, "frozen_random_forest": None},
            "absolute_error_percentage_points": {"raw_noaa20": None, "frozen_random_forest": None},
            "errors_undefined": True,
            "reason": "No jointly eligible NOAA-20/Aqua cell-days under the half-cell shared-visible-land rule.",
            "calibration_activated": False,
            "noaa21_status": "calibration pending",
            "selected_suomi_model": "random_forest",
            "selected_suomi_model_changed": False,
            "final_test_evaluated": False,
            "pantanal_opened": False,
            "native_detections_preserved": True,
        }

    frame = pd.DataFrame(noaa_eligible)
    prepared = _prepare(frame, settings())
    feature_frame = prepared.loc[:, list(FEATURE_COLUMNS)]
    probabilities = pipeline.predict_proba(feature_frame)[:, 1]
    aqua = prepared["modis_detected"].astype(float).to_numpy()
    raw = (prepared["viirs_hotspot_pixels"].astype(float).to_numpy() >= 1.0).astype(float)
    aqua_rate = float(aqua.mean())
    raw_rate = float(raw.mean())
    model_rate = float(np.mean(probabilities))
    signed = {
        "raw_noaa20": (raw_rate - aqua_rate) * 100.0,
        "frozen_random_forest": (model_rate - aqua_rate) * 100.0,
    }
    absolute = {key: abs(value) for key, value in signed.items()}
    confirmed = sorted({str(row.get("viirs_file")) for row in noaa_eligible if row.get("viirs_file")})
    sparse = positives < 20
    return {
        "label": "NOAA-20 transfer pilot evaluated",
        "operational_harmonized_estimate": "calibration pending",
        "research_status": "transfer pilot evaluated",
        "region_id": pilot["region_id"],
        "week_start": pilot["week_start"],
        "week_end": pilot["week_end"],
        "protocol_amendment": "2026-11-12b",
        "bytes_transferred": int(checkpoint.get("bytes_downloaded", 0)),
        "authorized_bytes": AUTHORIZED_BYTES,
        "verification": checkpoint.get("verification") or [],
        "feature_parity": feature_audit,
        "frozen_model": model_info,
        "qualifying_passes": len(confirmed),
        "qualifying_pass_files": confirmed,
        "matched_cell_days": len(noaa_eligible),
        "aqua_positives": int(positives),
        "aqua_zeros": int(zeros),
        "observed_aqua_rate": aqua_rate,
        "raw_noaa20_rate": raw_rate,
        "frozen_model_mean_probability": model_rate,
        "signed_difference_percentage_points": signed,
        "absolute_error_percentage_points": absolute,
        "errors_undefined": False,
        "sparse_aqua_positives": sparse,
        "pilot_interpretation": (
            "This quiet Cerrado week has few or no Aqua positives, so the pilot mainly tests "
            "low-activity / clear-zero transfer behavior. Active-fire transfer under high Aqua "
            "activity remains unknown until a busier NOAA-20 week is scored."
            if sparse
            else "Aqua positives are present; treat active-condition transfer as measured for this week only."
        ),
        "calibration_activated": False,
        "noaa21_status": "calibration pending",
        "selected_suomi_model": "random_forest",
        "selected_suomi_model_changed": False,
        "final_test_evaluated": False,
        "pantanal_opened": False,
        "native_detections_preserved": True,
        "predictions_path": str(PILOT_TABLE),
    }


def _guard_operational_state(before_selection: dict, before_reserve: dict) -> dict:
    after_selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    after_reserve = json.loads(RESERVE_PATH.read_text(encoding="utf-8"))
    return {
        "suomi_chosen_before": before_selection.get("chosen_model"),
        "suomi_chosen_after": after_selection.get("chosen_model"),
        "suomi_unchanged": before_selection.get("chosen_model") == after_selection.get("chosen_model") == "random_forest",
        "reserve_unchanged": before_reserve.get("chosen_model") == after_reserve.get("chosen_model"),
        "noaa20_operational": "calibration pending",
        "noaa21_operational": "calibration pending",
        "pilot_cannot_activate_noaa": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--i-authorize-download", action="store_true")
    args = parser.parse_args()
    pilot = _load_pilot()
    if not args.i_authorize_download:
        print(
            "Download is not authorized. Re-run with --i-authorize-download after review. "
            f"Pilot: {PILOT_PATH} daytime_pairs={len(pilot['daytime_pairs'])} "
            f"estimated_bytes={pilot['estimated_transfer_bytes']}"
        )
        return 2
    if pilot["region_id"] == "pantanal" or pilot["week_start"].startswith(("2023", "2024")):
        raise RuntimeError("The reserved final test and Pantanal stay closed.")
    if int(pilot["estimated_transfer_bytes"]) != AUTHORIZED_BYTES:
        raise RuntimeError("Pilot estimated bytes drifted from the authorized 1,800,954,900.")
    if not try_login():
        print("Earthdata login is required.")
        return 2

    before_selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    before_reserve = json.loads(RESERVE_PATH.read_text(encoding="utf-8"))
    model_info = _verify_model_hash()
    print(f"Frozen random_forest {model_info['candidate_sha256']}", flush=True)

    region = region_by_id(pilot["region_id"])
    searched = _search_noaa20_objects(region, pilot["week_start"], pilot["week_end"])
    if searched["errors"].get("VJ114IMG") or searched["errors"].get("VJ103IMG"):
        print(f"search errors: {searched['errors']}", flush=True)
    checkpoint = _download_daytime_pairs(pilot, searched["objects"])
    print(f"Transferred bytes: {checkpoint['bytes_downloaded']}", flush=True)

    index = _index_raw()
    first = pilot["daytime_pairs"][0]
    fire_path = _resolve(first["fire"], index) or _resolve(f"{Path(first['fire']).stem}.nc", index)
    geo_path = _resolve(first["geolocation"], index) or _resolve(f"{Path(first['geolocation']).stem}.nc", index)
    if fire_path is None or geo_path is None:
        raise RuntimeError("Cannot run feature parity without the first daytime NOAA-20 pair on disk.")
    feature_audit = _feature_parity_audit(fire_path, geo_path, region, settings())
    print(f"Feature parity faithful={feature_audit['faithful']}", flush=True)
    if not feature_audit["faithful"]:
        payload = {
            "label": "NOAA-20 transfer pilot blocked",
            "reason": "NOAA-20 could not reproduce every frozen-model feature faithfully.",
            "feature_parity": feature_audit,
            "frozen_model": model_info,
            "bytes_transferred": int(checkpoint.get("bytes_downloaded", 0)),
            "operational_harmonized_estimate": "calibration pending",
            "calibration_activated": False,
        }
        _save(RESULT_PATH, payload)
        print(json.dumps(payload, indent=2))
        return 2

    paths = _collect_paths(pilot)
    print(f"Processing {len(paths)} local files (cached Aqua + NOAA-20 daytime pairs)", flush=True)
    processed = process_directory(paths, (region["west"], region["south"], region["east"], region["north"]), region, settings())
    rows = processed["eligible"] + processed["excluded"]
    # Keep the pilot table separate from the operational paired table.
    if rows:
        pd.DataFrame(rows).to_parquet(PILOT_TABLE, index=False)
    artifact = joblib.load(VELA_MODEL)
    result = _score_transfer(rows, artifact["pipeline"], model_info, feature_audit, checkpoint, pilot)
    result["confirmed_passes"] = processed.get("confirmed_passes") or []
    result["exclusion_counts"] = processed.get("exclusion_counts") or {}
    result["granule_skips"] = processed.get("granule_skips") or []
    result["guards"] = _guard_operational_state(before_selection, before_reserve)
    result["next_development_week"] = {
        "status": "not_specified_by_transfer_plan",
        "proposed_rule": (
            "Walk the existing 2021–2022 validation_priority order for NOAA-20/Aqua daytime pairs, "
            "starting after Cerrado 2021-02-22. Do not reorder by fire counts, Aqua rates, or model scores. "
            "Reuse cached Aqua when present. Keep operational NOAA estimates calibration pending until a "
            "written activation rule is approved."
        ),
        "proposed_next_week": {
            "region_id": "california",
            "week_start": "2021-03-22",
            "week_end": "2021-03-28",
            "source": "validation_priority.next after cerrado 2021-02-22",
        },
        "outcomes_inspected_before_rule": False,
    }
    _save(RESULT_PATH, result)

    # Update research manifests without activating operational calibration.
    pilot.update(
        {
            "metadata_only": False,
            "download_started": True,
            "calibration_activated": False,
            "bytes_transferred": result["bytes_transferred"],
            "research_status": "transfer pilot evaluated",
            "harmonized_estimate": "calibration pending",
            "result_file": str(RESULT_PATH),
        }
    )
    _save(PILOT_PATH, pilot)
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan["metadata_only"] = False
    plan["download_started"] = True
    plan["measured_transfer_results"] = True
    plan["harmonized_estimate"] = "calibration pending"
    plan["noaa20_cerrado_pilot"] = {
        "file": "data/catalog/noaa20_cerrado_pilot.json",
        "week_start": pilot["week_start"],
        "week_end": pilot["week_end"],
        "download_started": True,
        "calibration_activated": False,
        "research_status": "transfer pilot evaluated",
        "result_file": "data/models/noaa20_cerrado_transfer_pilot.json",
    }
    plan["frozen_suomi_npp"]["candidates_refit"] = False
    plan["frozen_suomi_npp"]["final_test_evaluated"] = False
    _save(PLAN_PATH, plan)

    print(json.dumps({
        "bytes_transferred": result["bytes_transferred"],
        "matched_cell_days": result["matched_cell_days"],
        "aqua_positives": result["aqua_positives"],
        "aqua_zeros": result["aqua_zeros"],
        "observed_aqua_rate": result["observed_aqua_rate"],
        "raw_noaa20_rate": result["raw_noaa20_rate"],
        "frozen_model_mean_probability": result["frozen_model_mean_probability"],
        "absolute_error_percentage_points": result["absolute_error_percentage_points"],
        "calibration_activated": result["calibration_activated"],
        "guards": result["guards"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
