"""Metadata + cache audit: Aqua matches for the Cerrado NOAA-20 pilot passes.

Authorizes Earthdata metadata search and local processing only. Does not
download Aqua granules. Preserves the original cache-limited pilot record.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from scripts.process_matched_passes import _index_raw, _resolve
from vela.features import FEATURE_COLUMNS
from vela.geo import boxes_overlap, local_hour
from vela.pairing import complete_passes, index_passes, parse_granule_name
from vela.pipeline import describe_granule, process_directory, search_product, try_login
from vela.settings import DATA_DIR, region_by_id, settings
from vela.train import _prepare

PILOT_PATH = DATA_DIR / "catalog" / "noaa20_cerrado_pilot.json"
ORIGINAL_RESULT = DATA_DIR / "models" / "noaa20_cerrado_transfer_pilot.json"
AUDIT_PATH = DATA_DIR / "catalog" / "noaa20_cerrado_aqua_archive_audit.json"
AQUA_MANIFEST = DATA_DIR / "catalog" / "noaa20_cerrado_missing_aqua_manifest.json"
RERUN_RESULT = DATA_DIR / "models" / "noaa20_cerrado_transfer_pilot_archive_aware.json"
CALIFORNIA_INV = DATA_DIR / "catalog" / "noaa20_california_2021-03-22_inventory.json"
WEEK_ORDER = DATA_DIR / "catalog" / "noaa20_transfer_week_order.json"
PILOT_TABLE = DATA_DIR / "processed" / "noaa20_cerrado_pilot_cells_archive_aware.parquet"


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _record_week_order() -> dict:
    """Fixed before inspecting further fire outcomes."""

    order = {
        "recorded_before_further_fire_outcomes": True,
        "rule": (
            "Follow the existing 2021–2022 validation_priority order for NOAA-20/Aqua "
            "transfer weeks. Do not reorder by fire counts, Aqua rates, or model scores."
        ),
        "order": [
            {"region_id": "cerrado", "week_start": "2021-02-22", "week_end": "2021-02-28", "role": "pilot"},
            {"region_id": "california", "week_start": "2021-03-22", "week_end": "2021-03-28", "role": "next"},
            {"region_id": "zambia", "week_start": "2021-07-19", "week_end": "2021-07-25", "role": "later"},
            {"region_id": "yakutia", "week_start": "2021-11-22", "week_end": "2021-11-28", "role": "later"},
            {"region_id": "arnhem", "week_start": "2022-11-28", "week_end": "2022-12-04", "role": "later"},
        ],
        "next": {"region_id": "california", "week_start": "2021-03-22", "week_end": "2021-03-28"},
        "operational_noaa20": "calibration pending",
        "suomi_model": "random_forest",
        "held_out_untouched": ["2023-2024", "pantanal"],
    }
    _save(WEEK_ORDER, order)
    return order


def _search_aqua(region: dict, start: str, end: str) -> dict:
    cfg = settings()
    bbox = (region["west"], region["south"], region["east"], region["north"])
    objects = {}
    described = []
    versions = {}
    errors = {}
    query_status = {}
    for key in ("MYD14", "MYD03"):
        product = cfg["products"][key]
        try:
            results, version, error = search_product(product["short_name"], product["version"], bbox, start, end)
        except Exception as exc:  # noqa: BLE001
            versions[key] = None
            errors[key] = str(exc)
            query_status[key] = "failed"
            continue
        versions[key] = version
        errors[key] = error
        if error and not results:
            query_status[key] = "failed"
        elif results is None:
            query_status[key] = "incomplete"
        else:
            query_status[key] = "ok"
        for granule in results or []:
            info = describe_granule(granule)
            if not info.get("name"):
                continue
            info["product"] = key
            described.append(info)
            objects[info["name"]] = granule
            objects[Path(info["name"]).stem] = granule
    return {
        "objects": objects,
        "described": described,
        "versions": versions,
        "errors": errors,
        "query_status": query_status,
        "bbox": list(bbox),
    }


def _complete_aqua_from_catalog(described: list[dict]) -> tuple[list[dict], list[dict]]:
    names = [item["name"] for item in described if item.get("name")]
    passes, unrecognized = index_passes(names)
    # Attach catalog boxes/sizes onto pass slots.
    by_name = {item["name"]: item for item in described if item.get("name")}
    by_stem = {Path(item["name"]).stem: item for item in described if item.get("name")}
    enriched = []
    for item in passes:
        fire_meta = by_name.get(item["fire_name"]) or by_stem.get(Path(item["fire_name"] or "").stem)
        geo_meta = by_name.get(item["geo_name"]) or by_stem.get(Path(item["geo_name"] or "").stem)
        boxes = []
        if fire_meta:
            boxes.extend(fire_meta.get("boxes") or [])
        if geo_meta:
            boxes.extend(geo_meta.get("boxes") or [])
        bytes_total = None
        if fire_meta and geo_meta and fire_meta.get("size_bytes") is not None and geo_meta.get("size_bytes") is not None:
            bytes_total = int(fire_meta["size_bytes"]) + int(geo_meta["size_bytes"])
        enriched.append(
            {
                **item,
                "boxes": boxes,
                "fire_bytes": None if fire_meta is None else fire_meta.get("size_bytes"),
                "geo_bytes": None if geo_meta is None else geo_meta.get("size_bytes"),
                "pair_bytes": bytes_total,
                "fire_catalog": fire_meta,
                "geo_catalog": geo_meta,
            }
        )
    ready, incomplete = complete_passes(enriched)
    return ready, incomplete + [{"stamp": name, "missing": "unrecognized"} for name in unrecognized]


def _footprint_overlaps_region(boxes: list, bbox: tuple[float, float, float, float]) -> tuple[bool | None, str]:
    """Catalog footprint check only. Not measured shared visible land.

    CMR granule searches already use the study bbox, so a hit with empty UMM
    rectangles is treated as catalog-level overlap via the search filter.
    """

    if boxes:
        return any(boxes_overlap(tuple(box), bbox) for box in boxes), "umm_bounding_rectangles"
    return True, "cmr_bbox_search_hit_umm_rectangles_empty"


def _cache_status(fire_name: str | None, geo_name: str | None, index: dict) -> dict:
    fire_path = None if not fire_name else (_resolve(fire_name, index) or _resolve(f"{Path(fire_name).stem}.hdf", index))
    geo_path = None if not geo_name else (_resolve(geo_name, index) or _resolve(f"{Path(geo_name).stem}.hdf", index))
    if fire_path and geo_path:
        status = "cached"
    elif fire_path or geo_path:
        status = "partially_cached"
    else:
        status = "missing"
    return {
        "cache_status": status,
        "fire_cached": fire_path is not None,
        "geo_cached": geo_path is not None,
        "fire_path": None if fire_path is None else str(fire_path),
        "geo_path": None if geo_path is None else str(geo_path),
    }


def _audit_noaa_passes(pilot: dict, aqua_ready: list[dict], region: dict, query_status: dict) -> list[dict]:
    cfg = settings()
    tolerance = float(cfg["pair_tolerance_minutes"])
    bbox = (region["west"], region["south"], region["east"], region["north"])
    index = _index_raw()
    center_lon = (float(region["west"]) + float(region["east"])) / 2
    rows = []
    aqua_query_ok = query_status.get("MYD14") == "ok" and query_status.get("MYD03") == "ok"
    for pair in pilot["daytime_pairs"]:
        noaa_when = datetime.fromisoformat(pair["when"])
        if noaa_when.tzinfo is None:
            noaa_when = noaa_when.replace(tzinfo=timezone.utc)
        best = None
        for aqua in aqua_ready:
            delta = abs(noaa_when - aqua["when"]).total_seconds() / 60.0
            if best is None or delta < best[0]:
                best = (delta, aqua)
        if not aqua_query_ok:
            rows.append(
                {
                    "noaa20_fire": pair["fire"],
                    "noaa20_geolocation": pair["geolocation"],
                    "noaa20_acquisition_time": pair["when"],
                    "noaa20_local_hour": pair.get("local_hour"),
                    "best_candidate_aqua_time": None,
                    "best_candidate_aqua_stamp": None,
                    "time_difference_minutes": None,
                    "footprint_overlap_study_box": None,
                    "cache_status": "unknown",
                    "within_30_minutes": None,
                    "decision": "excluded",
                    "reason": (
                        "Aqua archive query incomplete or failed; cannot distinguish absence of a match "
                        f"from a search problem (MYD14={query_status.get('MYD14')}, MYD03={query_status.get('MYD03')})."
                    ),
                    "query_status": dict(query_status),
                }
            )
            continue
        if best is None:
            rows.append(
                {
                    "noaa20_fire": pair["fire"],
                    "noaa20_geolocation": pair["geolocation"],
                    "noaa20_acquisition_time": pair["when"],
                    "noaa20_local_hour": pair.get("local_hour"),
                    "best_candidate_aqua_time": None,
                    "best_candidate_aqua_stamp": None,
                    "time_difference_minutes": None,
                    "footprint_overlap_study_box": None,
                    "cache_status": "n/a",
                    "within_30_minutes": False,
                    "decision": "excluded",
                    "reason": "confirmed_no_catalog_aqua_fire_geo_pair_in_week_search",
                    "query_status": dict(query_status),
                }
            )
            continue
        delta, aqua = best
        overlap, overlap_evidence = _footprint_overlaps_region(aqua.get("boxes") or [], bbox)
        cache = _cache_status(aqua.get("fire_name"), aqua.get("geo_name"), index)
        aqua_day = float(cfg["daytime_local_hour_min"]) <= local_hour(aqua["when"], center_lon) <= float(cfg["daytime_local_hour_max"])
        noaa_day = float(cfg["daytime_local_hour_min"]) <= float(pair.get("local_hour") or local_hour(noaa_when, center_lon)) <= float(
            cfg["daytime_local_hour_max"]
        )
        within = delta <= tolerance + 1e-9
        if not within:
            decision = "excluded"
            reason = f"best_aqua_outside_{int(tolerance)}_minute_window"
        elif overlap is False:
            decision = "excluded"
            reason = "catalog_footprint_does_not_overlap_study_box"
        elif not aqua_day or not noaa_day:
            decision = "excluded"
            reason = "outside_daytime_local_hour_window"
        else:
            decision = "accepted_catalog_pair"
            reason = "within_30_min_daytime_and_catalog_footprint_overlaps_study_box"
        rows.append(
            {
                "noaa20_fire": pair["fire"],
                "noaa20_geolocation": pair["geolocation"],
                "noaa20_acquisition_time": pair["when"],
                "noaa20_local_hour": pair.get("local_hour"),
                "best_candidate_aqua_time": aqua["when"].isoformat(),
                "best_candidate_aqua_stamp": aqua["stamp"],
                "best_candidate_aqua_fire": aqua.get("fire_name"),
                "best_candidate_aqua_geolocation": aqua.get("geo_name"),
                "time_difference_minutes": round(delta, 3),
                "footprint_overlap_study_box": overlap,
                "footprint_evidence": overlap_evidence,
                "catalog_pair_bytes": aqua.get("pair_bytes"),
                **cache,
                "within_30_minutes": within,
                "aqua_daytime_local_hour_ok": aqua_day,
                "noaa20_daytime_local_hour_ok": noaa_day,
                "decision": decision,
                "reason": reason,
                "note": (
                    "Catalog footprint overlap is not measured shared visible land. "
                    "Shared visible land is evaluated only after reading both swaths."
                ),
                "query_status": dict(query_status),
            }
        )
    return rows


def _missing_aqua_manifest(rows: list[dict], aqua_ready: list[dict]) -> dict:
    sizes = {}
    for aqua in aqua_ready:
        if aqua.get("fire_name") and aqua.get("fire_bytes") is not None:
            sizes[aqua["fire_name"]] = int(aqua["fire_bytes"])
            sizes[Path(aqua["fire_name"]).stem] = int(aqua["fire_bytes"])
        if aqua.get("geo_name") and aqua.get("geo_bytes") is not None:
            sizes[aqua["geo_name"]] = int(aqua["geo_bytes"])
            sizes[Path(aqua["geo_name"]).stem] = int(aqua["geo_bytes"])
    stamps_seen = set()
    dedup_pairs = []
    missing_files = {}
    estimated = 0
    unknown = False
    for row in rows:
        if row["decision"] != "accepted_catalog_pair":
            continue
        if row["cache_status"] == "cached":
            continue
        stamp = row["best_candidate_aqua_stamp"]
        if stamp in stamps_seen:
            continue
        stamps_seen.add(stamp)
        fire = row.get("best_candidate_aqua_fire")
        geo = row.get("best_candidate_aqua_geolocation")
        needed = []
        pair_extra = 0
        pair_unknown = False
        if fire and not row.get("fire_cached"):
            needed.append(fire)
            missing_files[fire] = {"name": fire, "role": "fire", "aqua_stamp": stamp, "bytes": sizes.get(fire) or sizes.get(Path(fire).stem)}
            if missing_files[fire]["bytes"] is None:
                pair_unknown = True
            else:
                pair_extra += int(missing_files[fire]["bytes"])
        if geo and not row.get("geo_cached"):
            needed.append(geo)
            missing_files[geo] = {"name": geo, "role": "geolocation", "aqua_stamp": stamp, "bytes": sizes.get(geo) or sizes.get(Path(geo).stem)}
            if missing_files[geo]["bytes"] is None:
                pair_unknown = True
            else:
                pair_extra += int(missing_files[geo]["bytes"])
        dedup_pairs.append(
            {
                "aqua_stamp": stamp,
                "fire": fire,
                "geolocation": geo,
                "missing_files": needed,
                "additional_bytes": None if pair_unknown else pair_extra,
                "catalog_pair_bytes": row.get("catalog_pair_bytes"),
                "cache_status": row["cache_status"],
                "noaa20_fire": row["noaa20_fire"],
            }
        )
        if pair_unknown:
            unknown = True
        else:
            estimated += pair_extra
    command = (
        "PYTHONUNBUFFERED=1 python -m scripts.ingest_noaa20_cerrado_aqua "
        "--manifest data/catalog/noaa20_cerrado_missing_aqua_manifest.json "
        "--i-authorize-download"
    )
    return {
        "label": "noaa20-cerrado-missing-aqua",
        "download_authorized_this_run": False,
        "reuse_noaa20_files": 20,
        "deduplicated_missing_aqua_pairs": dedup_pairs,
        "missing_files": sorted(missing_files.values(), key=lambda item: item["name"]),
        "missing_file_names": sorted(missing_files),
        "estimated_additional_bytes": None if unknown else estimated,
        "catalog_overlap_vs_measured_shared_land": (
            "Accepted rows used catalog footprint overlap with the study box "
            "(UMM rectangles when present, otherwise CMR bbox search hit). "
            "Measured shared visible land is computed only after both swaths are read."
        ),
        "exact_retrieve_command": command,
    }


def _process_cached_accepted(rows: list[dict], pilot: dict, region: dict) -> dict | None:
    accepted_cached = [row for row in rows if row["decision"] == "accepted_catalog_pair" and row["cache_status"] == "cached"]
    if not accepted_cached:
        return None
    index = _index_raw()
    paths = []
    for row in accepted_cached:
        for name in (row["best_candidate_aqua_fire"], row["best_candidate_aqua_geolocation"], row["noaa20_fire"], row["noaa20_geolocation"]):
            path = _resolve(name, index) or _resolve(f"{Path(name).stem}.nc", index) or _resolve(f"{Path(name).stem}.hdf", index)
            if path is None:
                raise RuntimeError(f"Accepted cached file missing on disk: {name}")
            paths.append(str(path))
    paths = sorted(set(paths))
    processed = process_directory(paths, (region["west"], region["south"], region["east"], region["north"]), region, settings())
    rows_out = processed["eligible"] + processed["excluded"]
    if rows_out:
        pd.DataFrame(rows_out).to_parquet(PILOT_TABLE, index=False)
    eligible = [row for row in rows_out if row.get("outcome") == "eligible" and str(row.get("viirs_platform")) == "NOAA-20"]
    original = json.loads(ORIGINAL_RESULT.read_text(encoding="utf-8"))
    result = {
        "label": "NOAA-20 transfer pilot archive-aware rerun",
        "preserves_original_cache_limited_pilot": str(ORIGINAL_RESULT),
        "original_matched_cell_days": original.get("matched_cell_days"),
        "operational_harmonized_estimate": "calibration pending",
        "research_status": "transfer pilot evaluated",
        "region_id": pilot["region_id"],
        "week_start": pilot["week_start"],
        "week_end": pilot["week_end"],
        "accepted_cached_catalog_pairs": len(accepted_cached),
        "confirmed_passes": processed.get("confirmed_passes") or [],
        "exclusion_counts": processed.get("exclusion_counts") or {},
        "granule_skips": processed.get("granule_skips") or [],
        "calibration_activated": False,
        "selected_suomi_model": "random_forest",
        "selected_suomi_model_changed": False,
        "noaa21_status": "calibration pending",
        "final_test_evaluated": False,
        "pantanal_opened": False,
    }
    if not eligible:
        result.update(
            {
                "matched_cell_days": 0,
                "aqua_positives": 0,
                "aqua_zeros": 0,
                "observed_aqua_rate": None,
                "raw_noaa20_rate": None,
                "frozen_model_mean_probability": None,
                "signed_difference_percentage_points": {"raw_noaa20": None, "frozen_random_forest": None},
                "absolute_error_percentage_points": {"raw_noaa20": None, "frozen_random_forest": None},
                "errors_undefined": True,
                "reason": "Accepted cached Aqua/NOAA-20 catalog pairs still yielded zero jointly eligible cell-days after measured shared visible land.",
            }
        )
        _save(RERUN_RESULT, result)
        return result
    artifact = joblib.load(DATA_DIR / "models" / "vela_model.joblib")
    frame = _prepare(pd.DataFrame(eligible), settings())
    probs = artifact["pipeline"].predict_proba(frame.loc[:, list(FEATURE_COLUMNS)])[:, 1]
    aqua = frame["modis_detected"].astype(float).to_numpy()
    raw = (frame["viirs_hotspot_pixels"].astype(float).to_numpy() >= 1.0).astype(float)
    aqua_rate = float(aqua.mean())
    raw_rate = float(raw.mean())
    model_rate = float(np.mean(probs))
    result.update(
        {
            "matched_cell_days": len(eligible),
            "aqua_positives": int(aqua.sum()),
            "aqua_zeros": int(len(eligible) - aqua.sum()),
            "observed_aqua_rate": aqua_rate,
            "raw_noaa20_rate": raw_rate,
            "frozen_model_mean_probability": model_rate,
            "signed_difference_percentage_points": {
                "raw_noaa20": (raw_rate - aqua_rate) * 100.0,
                "frozen_random_forest": (model_rate - aqua_rate) * 100.0,
            },
            "absolute_error_percentage_points": {
                "raw_noaa20": abs(raw_rate - aqua_rate) * 100.0,
                "frozen_random_forest": abs(model_rate - aqua_rate) * 100.0,
            },
            "errors_undefined": False,
            "frozen_model_sha256": original.get("frozen_model", {}).get("candidate_sha256"),
        }
    )
    _save(RERUN_RESULT, result)
    return result


def _california_inventory() -> dict:
    cfg = settings()
    region = region_by_id("california")
    start, end = "2021-03-22", "2021-03-28"
    bbox = (region["west"], region["south"], region["east"], region["north"])
    login = try_login()
    products = {
        "MYD14": cfg["products"]["MYD14"],
        "MYD03": cfg["products"]["MYD03"],
        "VJ114IMG": cfg["platform_transfer"]["products"]["VJ114IMG"],
        "VJ103IMG": cfg["platform_transfer"]["products"]["VJ103IMG"],
    }
    objects = {}
    described_by = {}
    versions = {}
    errors = {}
    query_status = {}
    for key, product in products.items():
        results, version, error = search_product(product["short_name"], product["version"], bbox, start, end)
        versions[key] = version
        errors[key] = error
        query_status[key] = "failed" if error and not results else "ok"
        described_by[key] = []
        for granule in results or []:
            info = describe_granule(granule)
            if not info.get("name"):
                continue
            info["product"] = key
            described_by[key].append(info)
            objects[info["name"]] = info
    aqua_ready, aqua_incomplete = _complete_aqua_from_catalog(described_by["MYD14"] + described_by["MYD03"])
    noaa_ready, noaa_incomplete = _complete_aqua_from_catalog(described_by["VJ114IMG"] + described_by["VJ103IMG"])
    # Filter daytime using region center and require catalog footprint overlap.
    center_lon = (float(region["west"]) + float(region["east"])) / 2

    def daytime_ok(when: datetime) -> bool:
        hour = local_hour(when, center_lon)
        return float(cfg["daytime_local_hour_min"]) <= hour <= float(cfg["daytime_local_hour_max"])

    aqua_day = [
        p
        for p in aqua_ready
        if daytime_ok(p["when"]) and _footprint_overlaps_region(p.get("boxes") or [], bbox)[0] is not False
    ]
    noaa_day = [
        p
        for p in noaa_ready
        if daytime_ok(p["when"]) and _footprint_overlaps_region(p.get("boxes") or [], bbox)[0] is not False
    ]
    tolerance = timedelta(minutes=float(cfg["pair_tolerance_minutes"]))
    pairs = []
    used_aqua = set()
    index = _index_raw()
    for noaa in sorted(noaa_day, key=lambda item: item["when"]):
        best = None
        for aqua in aqua_day:
            delta = abs(noaa["when"] - aqua["when"])
            if delta <= tolerance and (best is None or delta < best[0]):
                best = (delta, aqua)
        if best is None:
            continue
        delta, aqua = best
        used_aqua.add(aqua["stamp"])
        cache_aqua = _cache_status(aqua.get("fire_name"), aqua.get("geo_name"), index)
        cache_noaa = _cache_status(noaa.get("fire_name"), noaa.get("geo_name"), index)
        pairs.append(
            {
                "noaa20_stamp": noaa["stamp"],
                "noaa20_time": noaa["when"].isoformat(),
                "aqua_stamp": aqua["stamp"],
                "aqua_time": aqua["when"].isoformat(),
                "delta_minutes": delta.total_seconds() / 60.0,
                "aqua_fire": aqua.get("fire_name"),
                "aqua_geolocation": aqua.get("geo_name"),
                "noaa20_fire": noaa.get("fire_name"),
                "noaa20_geolocation": noaa.get("geo_name"),
                "aqua_cache_status": cache_aqua["cache_status"],
                "noaa20_cache_status": cache_noaa["cache_status"],
                "aqua_pair_bytes": aqua.get("pair_bytes"),
                "noaa20_pair_bytes": noaa.get("pair_bytes"),
                "catalog_footprint_overlap_checked": True,
                "measured_shared_visible_land": "not_computed_metadata_only",
            }
        )
    missing = {"Aqua": [], "NOAA-20": []}
    additional = 0
    unknown = False
    seen = set()
    for pair in pairs:
        for platform, fire, geo, cache_key, bytes_key in (
            ("Aqua", pair["aqua_fire"], pair["aqua_geolocation"], "aqua_cache_status", "aqua_pair_bytes"),
            ("NOAA-20", pair["noaa20_fire"], pair["noaa20_geolocation"], "noaa20_cache_status", "noaa20_pair_bytes"),
        ):
            if pair[cache_key] == "cached":
                continue
            stamp = (platform, fire, geo)
            if stamp in seen:
                continue
            seen.add(stamp)
            missing[platform].append({"fire": fire, "geolocation": geo, "pair_bytes": pair.get(bytes_key), "cache_status": pair[cache_key]})
            if pair.get(bytes_key) is None:
                unknown = True
            else:
                additional += int(pair[bytes_key])
    payload = {
        "label": "noaa20-california-inventory",
        "metadata_only": True,
        "download_started": False,
        "download_authorized_this_run": False,
        "region_id": "california",
        "week_start": start,
        "week_end": end,
        "earthdata_login": bool(login),
        "query_status": query_status,
        "search_errors": errors,
        "versions": versions,
        "files_per_product": {key: len(described_by[key]) for key in products},
        "aqua_complete_pairs": len(aqua_ready),
        "noaa20_complete_pairs": len(noaa_ready),
        "aqua_incomplete": len(aqua_incomplete),
        "noaa20_incomplete": len(noaa_incomplete),
        "candidate_pass_pairs_within_30_minutes": pairs,
        "candidate_pair_count": len(pairs),
        "missing_files_by_platform": missing,
        "estimated_additional_bytes": None if unknown else additional,
        "operational_noaa20": "calibration pending",
        "suomi_model_unchanged": "random_forest",
        "held_out_untouched": True,
    }
    _save(CALIFORNIA_INV, payload)
    return payload


def main() -> int:
    if not try_login():
        print("Earthdata login required for Aqua archive metadata search.")
        return 2
    # Preserve original pilot record explicitly.
    original = Path(ORIGINAL_RESULT)
    preserved = DATA_DIR / "models" / "noaa20_cerrado_transfer_pilot_cache_limited_original.json"
    if original.is_file() and not preserved.is_file():
        shutil.copy2(original, preserved)
        print(f"Preserved original cache-limited pilot at {preserved}")

    week_order = _record_week_order()
    print(f"Recorded NOAA-20 week order; next={week_order['next']}")

    pilot = json.loads(PILOT_PATH.read_text(encoding="utf-8"))
    region = region_by_id(pilot["region_id"])
    aqua_search = _search_aqua(region, pilot["week_start"], pilot["week_end"])
    print(f"Aqua query status: {aqua_search['query_status']}")
    aqua_ready, aqua_incomplete = _complete_aqua_from_catalog(aqua_search["described"])
    print(f"Aqua complete fire/geo pairs in catalog: {len(aqua_ready)} incomplete={len(aqua_incomplete)}")
    rows = _audit_noaa_passes(pilot, aqua_ready, region, aqua_search["query_status"])
    accepted = [row for row in rows if row["decision"] == "accepted_catalog_pair"]
    accepted_cached = [row for row in accepted if row["cache_status"] == "cached"]
    accepted_missing = [row for row in accepted if row["cache_status"] != "cached"]
    manifest = _missing_aqua_manifest(rows, aqua_ready)
    _save(AQUA_MANIFEST, manifest)

    audit = {
        "label": "noaa20-cerrado-aqua-archive-audit",
        "region_id": pilot["region_id"],
        "week_start": pilot["week_start"],
        "week_end": pilot["week_end"],
        "pair_tolerance_minutes": settings()["pair_tolerance_minutes"],
        "aqua_query_status": aqua_search["query_status"],
        "aqua_search_errors": aqua_search["errors"],
        "aqua_versions": aqua_search["versions"],
        "aqua_complete_catalog_pairs": len(aqua_ready),
        "aqua_incomplete_catalog_pairs": len(aqua_incomplete),
        "noaa20_daytime_passes": len(pilot["daytime_pairs"]),
        "rows": rows,
        "accepted_catalog_pairs": len(accepted),
        "accepted_cached": len(accepted_cached),
        "accepted_missing_locally": len(accepted_missing),
        "catalog_overlap_vs_measured_shared_land": (
            "This audit records catalog footprint overlap with the study box only. "
            "Measured shared visible land requires reading both swaths."
        ),
        "missing_aqua_manifest": str(AQUA_MANIFEST),
        "original_pilot_preserved": str(preserved if preserved.is_file() else original),
        "week_order_file": str(WEEK_ORDER),
        "download_authorized_this_run": False,
    }
    _save(AUDIT_PATH, audit)
    for row in rows:
        print(
            f"{row['noaa20_acquisition_time']} best_aqua={row.get('best_candidate_aqua_time')} "
            f"dt={row.get('time_difference_minutes')} overlap={row.get('footprint_overlap_study_box')} "
            f"cache={row.get('cache_status')} {row['decision']}: {row['reason']}"
        )

    rerun = None
    if accepted_cached:
        print(f"Processing {len(accepted_cached)} accepted cached Aqua/NOAA-20 catalog pairs")
        rerun = _process_cached_accepted(rows, pilot, region)
        print(
            f"Rerun matched_cell_days={rerun.get('matched_cell_days')} "
            f"errors_undefined={rerun.get('errors_undefined')}"
        )
    else:
        print("No additional accepted Aqua pairs are fully cached.")

    california = None
    scorable = bool(rerun and not rerun.get("errors_undefined") and (rerun.get("matched_cell_days") or 0) > 0)
    if not accepted and not scorable:
        # No additional qualifying archive pairs beyond what the cache-limited pilot already saw,
        # or still zero eligible after cache reprocess → California metadata inventory.
        need_california = len(accepted) == 0 or (rerun is not None and not scorable and len(accepted_missing) == 0)
        # User: If Cerrado has no additional qualifying archive pairs, run California inventory.
        # "Additional" means beyond the original cache-limited finding. If archive finds pairs that
        # are only missing locally, do NOT jump to California yet — recommend completing Cerrado.
        if len(accepted) == 0:
            print("Cerrado has no qualifying archive Aqua pairs within rules; running California metadata inventory")
            california = _california_inventory()
            print(
                f"California candidate pairs={california['candidate_pair_count']} "
                f"additional_bytes={california['estimated_additional_bytes']}"
            )
        else:
            print("Cerrado has qualifying archive pairs; California inventory deferred pending Aqua retrieval decision")
    elif len(accepted_missing) == 0 and not scorable and len(accepted) == 0:
        california = _california_inventory()

    # Recommendation
    if aqua_search["query_status"].get("MYD14") != "ok" or aqua_search["query_status"].get("MYD03") != "ok":
        recommendation = {
            "action": "report_archive_query_blocker",
            "expected_new_transfer_bytes": None,
            "why": "Aqua metadata query did not complete cleanly; absence of matches cannot be confirmed.",
        }
    elif accepted_missing:
        recommendation = {
            "action": "complete_cerrado_with_listed_missing_aqua_files",
            "expected_new_transfer_bytes": manifest.get("estimated_additional_bytes"),
            "manifest": str(AQUA_MANIFEST),
            "command": manifest.get("exact_retrieve_command"),
            "why": (
                "The archive has qualifying Aqua fire/geo pairs inside the 30-minute window for one or more "
                "NOAA-20 passes, but those Aqua granules are not fully cached. Retrieving only those Aqua files "
                "and reusing the 20 verified NOAA-20 files would allow a measured shared-visible-land comparison "
                "of Aqua rate, raw NOAA-20 rate, and frozen RF mean on jointly eligible cell-days."
            ),
        }
    elif scorable:
        recommendation = {
            "action": "cerrado_scored_from_cached_aqua",
            "expected_new_transfer_bytes": 0,
            "why": "Cached qualifying Aqua pairs were enough to score the Cerrado pilot.",
            "result": str(RERUN_RESULT),
        }
    else:
        # No additional qualifying archive pairs (or only the already-processed cached ones with zero eligible).
        if california is None:
            california = _california_inventory()
        recommendation = {
            "action": "proceed_to_california_manifest",
            "expected_new_transfer_bytes": california.get("estimated_additional_bytes"),
            "inventory": str(CALIFORNIA_INV),
            "why": (
                "Cerrado has no additional qualifying Aqua archive pairs that can create new eligible "
                "NOAA-20/Aqua cell-days from cache alone. The next week under the fixed order is California "
                "22–28 March 2021; its metadata inventory lists candidate pairs and additional bytes."
            ),
        }

    audit["rerun_result"] = None if rerun is None else str(RERUN_RESULT)
    audit["california_inventory"] = None if california is None else str(CALIFORNIA_INV)
    audit["recommendation"] = recommendation
    _save(AUDIT_PATH, audit)
    print(json.dumps({"recommendation": recommendation, "accepted": len(accepted), "accepted_cached": len(accepted_cached), "accepted_missing": len(accepted_missing)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
