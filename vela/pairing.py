"""Pair fire masks with geolocation files, then pair Aqua with each VIIRS platform."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAME_RE = re.compile(
    r"(?P<product>MYD14|MYD03|VNP14IMG|VNP03IMG|VJ114IMG|VJ103IMG|VJ214IMG|VJ203IMG)"
    r"\.A(?P<date>\d{7})\.(?P<time>\d{4})\."
)

PLATFORM = {
    "MYD14": "Aqua",
    "MYD03": "Aqua",
    "VNP14IMG": "Suomi-NPP",
    "VNP03IMG": "Suomi-NPP",
    "VJ114IMG": "NOAA-20",
    "VJ103IMG": "NOAA-20",
    "VJ214IMG": "NOAA-21",
    "VJ203IMG": "NOAA-21",
}

VIIRS_PLATFORMS = ("Suomi-NPP", "NOAA-20", "NOAA-21")
FIRE_PRODUCTS = {"MYD14", "VNP14IMG", "VJ114IMG", "VJ214IMG"}
GEO_PRODUCTS = {"MYD03", "VNP03IMG", "VJ103IMG", "VJ203IMG"}


def parse_granule_name(path) -> dict | None:
    match = NAME_RE.search(Path(path).name)
    if not match:
        return None
    acquired = datetime.strptime(match.group("date"), "%Y%j").replace(tzinfo=timezone.utc)
    hour = int(match.group("time")[:2])
    minute = int(match.group("time")[2:])
    when = acquired.replace(hour=hour, minute=minute)
    return {
        "product": match.group("product"),
        "stamp": f"A{match.group('date')}.{match.group('time')}",
        "when": when,
        "platform": PLATFORM[match.group("product")],
        "path": str(path),
        "file_name": Path(path).name,
    }


def index_passes(paths: list[str]) -> tuple[list[dict], list[str]]:
    """Match fire and geolocation files that share an acquisition time."""

    grouped: dict[tuple[str, str], dict] = {}
    unrecognized: list[str] = []
    for path in paths:
        meta = parse_granule_name(path)
        if meta is None:
            unrecognized.append(str(path))
            continue
        slot = grouped.setdefault(
            (meta["platform"], meta["stamp"]),
            {
                "platform": meta["platform"],
                "stamp": meta["stamp"],
                "when": meta["when"],
                "fire": None,
                "geo": None,
                "fire_name": None,
                "geo_name": None,
            },
        )
        if meta["product"] in FIRE_PRODUCTS:
            slot["fire"] = meta["path"]
            slot["fire_name"] = meta["file_name"]
        elif meta["product"] in GEO_PRODUCTS:
            slot["geo"] = meta["path"]
            slot["geo_name"] = meta["file_name"]
    return list(grouped.values()), unrecognized


def complete_passes(passes: list[dict]) -> tuple[list[dict], list[dict]]:
    ready = []
    incomplete = []
    for item in passes:
        if item["fire"] and item["geo"]:
            ready.append(item)
        else:
            missing = "geolocation" if item["fire"] else "fire mask"
            incomplete.append({**item, "missing": missing})
    return ready, incomplete


def pair_platforms(modis_passes: list[dict], viirs_passes: list[dict], tolerance_minutes: float) -> dict:
    """Pair passes by acquisition time. Land overlap is confirmed after reading."""

    tolerance = timedelta(minutes=float(tolerance_minutes))
    pairs = []
    unmatched_modis = []
    used_viirs = set()
    for modis in sorted(modis_passes, key=lambda item: item["when"]):
        best = None
        for index, viirs in enumerate(viirs_passes):
            delta = abs(modis["when"] - viirs["when"])
            if delta <= tolerance and (best is None or delta < best[0]):
                best = (delta, index, viirs)
        if best is None:
            unmatched_modis.append(modis)
            continue
        used_viirs.add(best[1])
        pairs.append(
            {
                "modis": modis,
                "viirs": best[2],
                "delta_minutes": best[0].total_seconds() / 60.0,
            }
        )
    unmatched_viirs = [item for index, item in enumerate(viirs_passes) if index not in used_viirs]
    return {
        "pairs": pairs,
        "unmatched_modis": unmatched_modis,
        "unmatched_viirs": unmatched_viirs,
    }


def pair_each_viirs_platform(modis_passes: list[dict], viirs_passes: list[dict], tolerance_minutes: float) -> dict:
    """Match Aqua to Suomi-NPP, NOAA-20, and NOAA-21 separately.

    The same Aqua pass can pair with each platform. The platforms are not
    collapsed here; the calendar does that later, one cell-day at a time.
    """

    pairs = []
    unmatched_viirs = []
    for platform in VIIRS_PLATFORMS:
        subset = [item for item in viirs_passes if item["platform"] == platform]
        if not subset:
            continue
        paired = pair_platforms(modis_passes, subset, tolerance_minutes)
        for pair in paired["pairs"]:
            pair["viirs_platform"] = platform
        pairs.extend(paired["pairs"])
        unmatched_viirs.extend(paired["unmatched_viirs"])
    matched_modis = {id(pair["modis"]) for pair in pairs}
    unmatched_modis = [item for item in modis_passes if id(item) not in matched_modis]
    return {
        "pairs": pairs,
        "unmatched_modis": unmatched_modis,
        "unmatched_viirs": unmatched_viirs,
    }
