"""Discover the four swath products and turn a paired pass into cell rows."""

from __future__ import annotations

import gc
from datetime import datetime, timezone

import numpy as np

from vela.geo import boxes_overlap, local_hour
from vela.harmonize import (
    aggregate,
    choose_one,
    exclusion_summary,
    rows_for_pair,
    split_kept,
)
from vela.pairing import VIIRS_PLATFORMS, complete_passes, index_passes, pair_each_viirs_platform, pair_platforms
from vela.readers import read_pass

_SIZE_UNITS = {
    "B": 1,
    "BYTE": 1,
    "BYTES": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}


def try_login():
    """Use an existing Earthdata login. Never prompt in a non-interactive run."""

    import earthaccess

    for strategy in ("netrc", "environment"):
        try:
            auth = earthaccess.login(strategy=strategy, persist=False)
        except Exception:
            auth = None
        if auth:
            return auth
    return None


def _size_bytes(umm: dict) -> tuple[int | None, bool]:
    items = umm.get("DataGranule", {}).get("ArchiveAndDistributionInformation", [])
    total = 0
    found = False
    unknown = False
    for item in items:
        size = item.get("Size")
        if size is None:
            unknown = True
            continue
        unit = str(item.get("SizeUnit", "MB")).upper()
        factor = _SIZE_UNITS.get(unit)
        if factor is None:
            unknown = True
            continue
        total += int(round(float(size) * factor))
        found = True
    if not found:
        return None, True
    return total, unknown


def _rectangles(umm: dict) -> list[tuple[float, float, float, float]]:
    geometry = (
        umm.get("SpatialExtent", {})
        .get("HorizontalSpatialDomain", {})
        .get("Geometry", {})
        .get("BoundingRectangles", [])
    )
    boxes = []
    for rect in geometry:
        try:
            boxes.append(
                (
                    float(rect["WestBoundingCoordinate"]),
                    float(rect["SouthBoundingCoordinate"]),
                    float(rect["EastBoundingCoordinate"]),
                    float(rect["NorthBoundingCoordinate"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return boxes


def describe_granule(granule) -> dict:
    umm = granule["umm"] if isinstance(granule, dict) and "umm" in granule else granule.get("umm", granule)
    name = None
    for item in umm.get("DataGranule", {}).get("Identifiers", []):
        if item.get("IdentifierType") == "ProducerGranuleId" and item.get("Identifier"):
            name = item["Identifier"]
            break
    if name is None:
        try:
            links = granule.data_links()
        except Exception:
            links = []
        if links:
            name = str(links[0]).rstrip("/").split("/")[-1]
    size, unknown = _size_bytes(umm)
    begin = umm.get("TemporalExtent", {}).get("RangeDateTime", {}).get("BeginningDateTime")
    return {
        "name": name,
        "size_bytes": size,
        "size_unknown": unknown or size is None,
        "boxes": _rectangles(umm),
        "begin": begin,
    }


def _version_candidates(version: str) -> list[str]:
    text = str(version)
    ordered = [text]
    for item in {"061": ["6.1"], "6.1": ["061"], "002": ["2"], "2": ["002"]}.get(text, []):
        ordered.append(item)
    stripped = text.lstrip("0") or "0"
    padded = stripped.zfill(3)
    for item in (stripped, padded):
        if item not in ordered:
            ordered.append(item)
    return ordered


def search_product(short_name: str, version: str, bbox, start: str, end: str):
    import earthaccess

    last_error = None
    tried = _version_candidates(version)
    for candidate in tried:
        try:
            results = earthaccess.search_data(
                short_name=short_name,
                version=candidate,
                bounding_box=tuple(float(value) for value in bbox),
                temporal=(start, end),
                count=2000,
            )
        except Exception as exc:  # noqa: BLE001 - the catalog report shows this text
            last_error = exc
            continue
        if results:
            return results, candidate, None
    if last_error is not None:
        return [], tried[0], str(last_error)
    return [], tried[0], None


def _rough_daytime(when: datetime, bbox, config: dict) -> bool:
    west, south, east, north = bbox
    lon = (west + east) / 2 if west <= east else ((west + (east + 360)) / 2)
    if lon > 180:
        lon -= 360
    hour = local_hour(when, lon)
    return float(config["daytime_local_hour_min"]) <= hour <= float(config["daytime_local_hour_max"])


def _candidate_bytes(described: dict, pair: dict) -> int | None:
    total = 0
    for key in ("fire_name", "geo_name"):
        for side in ("modis", "viirs"):
            item = described.get(pair[side][key])
            if not item or item.get("size_bytes") is None:
                return None
            total += int(item["size_bytes"])
    return total


def build_catalog(product_hits: dict[str, list], bbox, config: dict) -> dict:
    """Summarize a metadata search. `product_hits` maps product id to described granules."""

    files = []
    unknown = []
    known_bytes = 0
    for product, granules in product_hits.items():
        for item in granules:
            files.append({**item, "product": product})
            if item.get("size_bytes") is None:
                unknown.append(item.get("name") or product)
            else:
                known_bytes += int(item["size_bytes"])
    unique_names = {}
    for item in files:
        unique_names.setdefault(item.get("name") or id(item), item)
    by_product = {}
    paths_for_pairing = []
    for item in unique_names.values():
        by_product.setdefault(item["product"], 0)
        by_product[item["product"]] += 1
        if item.get("name"):
            paths_for_pairing.append(item["name"])
    passes, unrecognized = index_passes(paths_for_pairing)
    modis = [item for item in passes if item["platform"] == "Aqua"]
    viirs = [item for item in passes if item["platform"] == "Suomi-NPP"]
    ready_modis, incomplete_modis = complete_passes(modis)
    ready_viirs, incomplete_viirs = complete_passes(viirs)
    paired = pair_platforms(ready_modis, ready_viirs, config["pair_tolerance_minutes"])
    described = {item["name"]: item for item in unique_names.values() if item.get("name")}
    candidates = []
    rejected = {"outside_daytime_window": 0, "footprint_outside_region": 0}
    for pair in paired["pairs"]:
        modis_meta = described.get(pair["modis"]["fire_name"])
        viirs_meta = described.get(pair["viirs"]["fire_name"])
        def _overlaps(meta) -> bool:
            if not meta or not meta.get("boxes"):
                return True
            return any(boxes_overlap(box, tuple(bbox)) for box in meta["boxes"])

        footprint_ok = _overlaps(modis_meta) and _overlaps(viirs_meta)
        daytime = _rough_daytime(pair["modis"]["when"], bbox, config) and _rough_daytime(
            pair["viirs"]["when"], bbox, config
        )
        if not footprint_ok:
            rejected["footprint_outside_region"] += 1
            continue
        if not daytime:
            rejected["outside_daytime_window"] += 1
            continue
        candidates.append(
            {
                "modis_fire": pair["modis"]["fire_name"],
                "modis_geo": pair["modis"]["geo_name"],
                "viirs_fire": pair["viirs"]["fire_name"],
                "viirs_geo": pair["viirs"]["geo_name"],
                "modis_time": pair["modis"]["when"].isoformat(),
                "viirs_time": pair["viirs"]["when"].isoformat(),
                "delta_minutes": round(pair["delta_minutes"], 2),
                "daytime_window": True,
                "bytes": _candidate_bytes(described, pair),
            }
        )
    return {
        "unique_files": len(unique_names),
        "files_per_product": by_product,
        "candidate_daytime_passes": candidates,
        "candidate_count": len(candidates),
        "estimated_transfer_bytes": known_bytes,
        "unknown_size_count": len(unknown),
        "unknown_size_files": unknown[:50],
        "incomplete_fire_geo_pairs": len(incomplete_modis) + len(incomplete_viirs),
        "modis_passes_without_viirs": len(paired["unmatched_modis"]),
        "viirs_passes_without_modis": len(paired["unmatched_viirs"]),
        "rejected": rejected,
        "unrecognized_names": unrecognized[:20],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def process_directory(files: list[str], bbox, region: dict, config: dict) -> dict:
    """Read paired daytime passes in the folder and aggregate them to the grid."""

    passes, unrecognized = index_passes(files)
    modis_passes = [item for item in passes if item["platform"] == "Aqua"]
    viirs_passes = [item for item in passes if item["platform"] in VIIRS_PLATFORMS]
    ready_modis, incomplete_modis = complete_passes(modis_passes)
    ready_viirs, incomplete_viirs = complete_passes(viirs_passes)
    paired = pair_each_viirs_platform(ready_modis, ready_viirs, config["pair_tolerance_minutes"])
    granule_skips = []
    for item in incomplete_modis + incomplete_viirs:
        granule_skips.append({"stamp": item["stamp"], "platform": item["platform"], "reason": f"missing_{item['missing']}"})
    for item in paired["unmatched_modis"]:
        granule_skips.append({"stamp": item["stamp"], "platform": "Aqua", "reason": "no_viirs_within_tolerance"})
    for item in paired["unmatched_viirs"]:
        granule_skips.append(
            {"stamp": item["stamp"], "platform": item["platform"], "reason": "no_modis_within_tolerance"}
        )
    collected = []
    confirmed = []
    for pair in paired["pairs"]:
        modis_read = read_pass(pair["modis"]["fire"], pair["modis"]["geo"], bbox, pair["modis"]["when"], config)
        if not modis_read["ok"]:
            granule_skips.append({"stamp": pair["modis"]["stamp"], "platform": "Aqua", "reason": modis_read["reason"]})
            continue
        viirs_read = read_pass(pair["viirs"]["fire"], pair["viirs"]["geo"], bbox, pair["viirs"]["when"], config)
        if not viirs_read["ok"]:
            granule_skips.append(
                {"stamp": pair["viirs"]["stamp"], "platform": pair["viirs"]["platform"], "reason": viirs_read["reason"]}
            )
            del modis_read
            gc.collect()
            continue
        modis_cells = aggregate(modis_read["lon"], modis_read["lat"], modis_read["classes"], "modis")
        viirs_cells = aggregate(viirs_read["lon"], viirs_read["lat"], viirs_read["classes"], "viirs")
        if not (set(modis_cells) & set(viirs_cells)):
            granule_skips.append(
                {
                    "stamp": pair["modis"]["stamp"],
                    "platform": "both",
                    "reason": "no_overlapping_land",
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
                "viirs_platform": pair["viirs"]["platform"],
            }
            collected.extend(rows_for_pair(modis_cells, viirs_cells, meta, config))
            confirmed.append(
                {
                    "modis_file": pair["modis"]["fire_name"],
                    "viirs_file": pair["viirs"]["fire_name"],
                    "viirs_platform": pair["viirs"]["platform"],
                    "delta_minutes": pair["delta_minutes"],
                    "modis_shape": modis_read["shape"],
                    "viirs_shape": viirs_read["shape"],
                    "modis_daytime_check": modis_read["daytime_check"],
                    "viirs_daytime_check": viirs_read["daytime_check"],
                    "modis_pixels_in_area": int(np.asarray(modis_read["classes"]).size),
                    "viirs_pixels_in_area": int(np.asarray(viirs_read["classes"]).size),
                }
            )
        del modis_read, viirs_read, modis_cells, viirs_cells
        gc.collect()
    kept, duplicates = choose_one(collected)
    eligible, excluded = split_kept(kept)
    excluded.extend(duplicates)
    return {
        "eligible": eligible,
        "excluded": excluded,
        "exclusion_counts": exclusion_summary(excluded),
        "granule_skips": granule_skips,
        "confirmed_passes": confirmed,
        "unrecognized_files": unrecognized,
        "outcome_counts": exclusion_summary(
            [{"exclusion_reason": row["outcome"]} for row in eligible]
        ),
    }
