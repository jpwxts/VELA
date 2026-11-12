"""Metadata-only NOAA-20 pilot for one Cerrado development week. Does not download."""

from __future__ import annotations

import json
from datetime import datetime

from vela.geo import local_hour
from vela.pipeline import describe_granule, try_login
from vela.discover import discover_week
from vela.platform_transfer import summarize_platform_granules
from vela.settings import DATA_DIR, region_by_id, settings

REGION_ID = "cerrado"
WEEK_START = "2021-02-22"
WEEK_END = "2021-02-28"


def _products(config: dict) -> dict:
    transfer = config.get("platform_transfer", {}).get("products", {})
    return {
        key: transfer[key]
        for key in ("VJ114IMG", "VJ103IMG")
        if key in transfer
    }


def build_pilot(config: dict | None = None) -> dict:
    cfg = config or settings()
    region = region_by_id(REGION_ID)
    search_config = {
        **cfg,
        "products": _products(cfg),
    }
    login = try_login()
    report, objects = discover_week(region, WEEK_START, WEEK_END, search_config)
    described = []
    for granule in objects.values():
        info = describe_granule(granule)
        if info.get("name"):
            described.append(info)
    summary = summarize_platform_granules(described, "NOAA-20")
    center_lon = (float(region["west"]) + float(region["east"])) / 2
    daytime = []
    night = []
    for pair in summary["matched_pairs"]:
        when = pair["when"]
        parsed = datetime.fromisoformat(when)
        hour = local_hour(parsed, center_lon)
        target = daytime if float(cfg["daytime_local_hour_min"]) <= hour <= float(cfg["daytime_local_hour_max"]) else night
        target.append({**pair, "local_hour": hour})
    unknown = [name for name in summary["unknown_size_files"]]
    daytime_bytes = None
    if daytime and all(pair["bytes"] is not None for pair in daytime):
        daytime_bytes = sum(pair["bytes"] for pair in daytime)
    return {
        "label": "noaa20-pilot",
        "metadata_only": True,
        "download_started": False,
        "calibration_activated": False,
        "fire_counts_used": False,
        "region_id": REGION_ID,
        "week_start": WEEK_START,
        "week_end": WEEK_END,
        "split": "tune",
        "chosen_before_scores": True,
        "reason": (
            "This is the first Cerrado week in the existing 2021–2022 validation order. "
            "It was fixed before any NOAA-20 fire counts were inspected."
        ),
        "products": ["VJ114IMG", "VJ103IMG"],
        "versions": report.get("versions"),
        "earthdata_login": bool(login),
        "search_errors": report.get("search_errors"),
        "files_per_product": report.get("files_per_product"),
        "matched_fire_geolocation_pairs": summary["matched_pairs"],
        "daytime_pairs": daytime,
        "outside_daytime_pairs": night,
        "unmatched": summary["unmatched"],
        "unrecognized": summary["unrecognized"],
        "unknown_size_files": unknown,
        "estimated_transfer_bytes": daytime_bytes,
        "all_matched_pair_bytes": summary["estimated_transfer_bytes"],
        "harmonized_estimate": "calibration pending",
        "noaa21_calibration": "calibration pending",
    }


def main() -> None:
    payload = build_pilot()
    destination = DATA_DIR / "catalog" / "noaa20_cerrado_pilot.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"noaa20 pilot {destination} pairs={len(payload['daytime_pairs'])} "
        f"unmatched={len(payload['unmatched'])} bytes={payload['estimated_transfer_bytes']} "
        f"download_started={payload['download_started']}"
    )


if __name__ == "__main__":
    main()
