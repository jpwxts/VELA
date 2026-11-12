"""Metadata-only plan for NOAA-20/Aqua and NOAA-21/Aqua transfer.

The frozen Suomi-NPP candidates and the 2023–2024 final test stay where they
are. NOAA-21 FIRMS coverage starts in 2023, so its evaluation cannot use the
final-test years. Nothing in this module downloads a granule.
"""

from __future__ import annotations

from vela.contributions import CONTRIBUTION_RULE
from vela.settings import settings

FINAL_TEST_YEARS = (2023, 2024)
NOAA20_FIRMS_START = "2018-04-01"
NOAA21_FIRMS_START = "2023-01-01"


def transfer_year(platform: str, year: int) -> str:
    """Assign a year without moving the existing final test."""

    value = int(year)
    if value in FINAL_TEST_YEARS:
        return "preserved_final_test"
    if platform == "NOAA-20" and 2021 <= value <= 2022:
        return "platform-transfer"
    if platform == "NOAA-21" and value >= 2025:
        return "platform-transfer"
    if platform == "NOAA-21" and value < 2023:
        return "before_firms_coverage"
    return "outside_platform_transfer"


def build_plan(config: dict | None = None) -> dict:
    cfg = config or settings()
    block = cfg.get("platform_transfer") or {}
    products = block.get("products") or {}
    return {
        "label": "platform-transfer",
        "metadata_only": True,
        "download_started": False,
        "fire_counts_used": False,
        "measured_transfer_results": False,
        "harmonized_estimate": "calibration pending",
        "preserved_final_test_years": list(FINAL_TEST_YEARS),
        "preserved_region": "pantanal",
        "frozen_suomi_npp": {
            "candidates_refit": False,
            "validation_file": "data/models/preliminary_validation.json",
            "validation_relabeled": False,
            "final_test_evaluated": False,
        },
        "products": products,
        "pairs": [
            {
                "viirs_platform": "NOAA-20",
                "reference_platform": "Aqua",
                "fire_product": "VJ114IMG",
                "geolocation_product": "VJ103IMG",
                "firms_coverage_start": block.get("noaa20_firms_start", NOAA20_FIRMS_START),
                "evaluation_years": [2021, 2022],
                "split": "platform-transfer",
                "reason": (
                    "NOAA-20 FIRMS coverage includes 2021–2022. "
                    "Those years are outside the 2023–2024 final test. "
                    "This plan does not rescore the frozen Suomi-NPP validation."
                ),
            },
            {
                "viirs_platform": "NOAA-21",
                "reference_platform": "Aqua",
                "fire_product": "VJ214IMG",
                "geolocation_product": "VJ203IMG",
                "firms_coverage_start": block.get("noaa21_firms_start", NOAA21_FIRMS_START),
                "evaluation_years": [2025, 2026],
                "excluded_years": list(FINAL_TEST_YEARS),
                "split": "platform-transfer",
                "reason": (
                    "NOAA-21 FIRMS coverage starts in 2023. "
                    "2023–2024 remain the Suomi-NPP final test, so the NOAA-21 transfer window starts in 2025."
                ),
            },
        ],
        "contribution_rule": CONTRIBUTION_RULE,
        "granule_search": "not_run",
        "estimated_transfer_bytes": None,
    }


def summarize_platform_granules(described: list[dict], platform: str) -> dict:
    """Pair fire and geolocation granules for one platform. This does not download."""

    from vela.pairing import complete_passes, index_passes

    sizes = {}
    paths = []
    for item in described:
        name = item.get("name")
        if not name:
            continue
        paths.append(name)
        sizes[name] = item.get("size_bytes")
    passes, unrecognized = index_passes(paths)
    ready, incomplete = complete_passes([item for item in passes if item.get("platform") == platform])
    matched = []
    unknown = []
    total = 0
    for item in sorted(ready, key=lambda row: row["when"]):
        fire_size = sizes.get(item["fire_name"])
        geo_size = sizes.get(item["geo_name"])
        pair_total = None
        if fire_size is None or geo_size is None:
            unknown.append(item["fire_name"] if fire_size is None else item["geo_name"])
        else:
            pair_total = int(fire_size) + int(geo_size)
            total += pair_total
        matched.append(
            {
                "when": item["when"].isoformat(),
                "fire": item["fire_name"],
                "geolocation": item["geo_name"],
                "bytes": pair_total,
            }
        )
    unmatched = [
        {
            "stamp": item["stamp"],
            "platform": item.get("platform"),
            "missing": item["missing"],
            "fire": item.get("fire_name"),
            "geolocation": item.get("geo_name"),
        }
        for item in incomplete
    ]
    return {
        "platform": platform,
        "matched_pairs": matched,
        "unmatched": unmatched,
        "unrecognized": unrecognized,
        "estimated_transfer_bytes": None if unknown else total,
        "unknown_size_files": unknown,
        "download_started": False,
        "calibration_activated": False,
    }
