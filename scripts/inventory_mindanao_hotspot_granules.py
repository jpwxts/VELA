"""CMR inventory of MYD14/MYD03 + VNP14IMG/VNP03IMG for Maguindanao hotspot windows.

Chooses a small pilot by coverage opportunity and file size before examining fire outcomes.
March 2019 is listed only as an optional reader smoke-test reference.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backfill_mindanao_firms_hotspot import DATE_WINDOWS
from vela.hotspot_coverage import HOTSPOT_DAILY_COVERAGE_RULE, INVENTORY_PATH, freeze_daily_coverage_rule
from vela.hotspot_forecast import STUDY
from vela.pipeline import describe_granule, search_product, try_login
from vela.pairing import complete_passes, index_passes
from vela.settings import DATA_DIR, settings

PRODUCTS = [
    ("MYD14", "061"),
    ("MYD03", "6.1"),
    ("VNP14IMG", "002"),
    ("VNP03IMG", "002"),
]


def _cache_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    root = DATA_DIR / "raw"
    if not root.exists():
        return index
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".hdf", ".nc", ".h5", ".hdf5"}:
            index[path.name] = path
    return index


def inventory_window(start: str, end: str, bbox: tuple[float, float, float, float]) -> dict:
    cfg = settings()
    product_hits: dict[str, list] = {}
    objects: dict[str, object] = {}
    for short, version in PRODUCTS:
        results, used_version, error = search_product(short, version, bbox, f"{start}T00:00:00", f"{end}T23:59:59")
        described = []
        for gran in results:
            item = describe_granule(gran)
            item["collection_version_used"] = used_version
            item["search_error"] = error
            described.append(item)
            if item.get("name"):
                objects[item["name"]] = gran
        product_hits[short] = described

    names = [item["name"] for items in product_hits.values() for item in items if item.get("name")]
    passes, unrecognized = index_passes(names)
    ready, incomplete = complete_passes(passes)
    cache = _cache_index()
    described_by_name = {
        item["name"]: item for items in product_hits.values() for item in items if item.get("name")
    }

    complete_meta = []
    for item in ready:
        fire_meta = described_by_name.get(item["fire_name"]) or {}
        geo_meta = described_by_name.get(item["geo_name"]) or {}
        fire_bytes = fire_meta.get("size_bytes")
        geo_bytes = geo_meta.get("size_bytes")
        total = None if fire_bytes is None or geo_bytes is None else int(fire_bytes) + int(geo_bytes)
        fire_hit = item["fire_name"] in cache
        geo_hit = item["geo_name"] in cache
        hour = item["when"].hour + item["when"].minute / 60.0
        # Rough daytime gate using UTC hour ≈ local for Mindanao (UTC+8 → local = UTC+8)
        local_hour = (hour + 8) % 24
        daytime = float(cfg["daytime_local_hour_min"]) <= local_hour <= float(cfg["daytime_local_hour_max"])
        complete_meta.append(
            {
                "platform": item["platform"],
                "stamp": item["stamp"],
                "when_utc": item["when"].isoformat(),
                "fire_name": item["fire_name"],
                "geo_name": item["geo_name"],
                "fire_bytes": fire_bytes,
                "geo_bytes": geo_bytes,
                "pair_bytes": total,
                "fire_cache_hit": fire_hit,
                "geo_cache_hit": geo_hit,
                "cache_complete": fire_hit and geo_hit,
                "daytime_local_rough": daytime,
                "local_hour_rough": round(local_hour, 2),
                "utc_date": item["when"].date().isoformat(),
            }
        )

    daytime_complete = [row for row in complete_meta if row["daytime_local_rough"]]
    transfer_needed = 0
    for row in daytime_complete:
        if row["cache_complete"]:
            continue
        if row["pair_bytes"] is None:
            continue
        on_disk = 0
        if row["fire_cache_hit"] and row["fire_bytes"]:
            on_disk += int(row["fire_bytes"])
        if row["geo_cache_hit"] and row["geo_bytes"]:
            on_disk += int(row["geo_bytes"])
        transfer_needed += max(int(row["pair_bytes"]) - on_disk, 0)

    return {
        "window": {"start": start, "end": end},
        "products": {
            short: {
                "count": len(product_hits[short]),
                "bytes": sum(int(i["size_bytes"]) for i in product_hits[short] if i.get("size_bytes") is not None),
            }
            for short, _ in PRODUCTS
        },
        "complete_fire_geo_pairs": len(complete_meta),
        "daytime_complete_pairs": len(daytime_complete),
        "incomplete_pairs": len(incomplete),
        "unrecognized_names": unrecognized[:20],
        "estimated_daytime_transfer_bytes": transfer_needed,
        "daytime_pairs": sorted(daytime_complete, key=lambda r: (r["pair_bytes"] is None, r["pair_bytes"] or 10**18)),
        "objects_keyed": list(objects.keys()),
    }


def choose_pilot(windows: list[dict], *, max_pair_bytes: int = 80_000_000) -> dict | None:
    """Smallest daytime Aqua (preferred) or VIIRS complete pair under the byte budget."""

    candidates = []
    for window in windows:
        for row in window.get("daytime_pairs") or []:
            if row.get("pair_bytes") is None:
                continue
            if int(row["pair_bytes"]) > max_pair_bytes:
                continue
            # Prefer Aqua (smaller MYD03) and cache hits; never prefer by fire outcome.
            score = (
                0 if row["platform"] == "Aqua" else 1,
                0 if row["cache_complete"] else 1,
                int(row["pair_bytes"]),
                row["when_utc"],
            )
            candidates.append((score, {**row, "window": window["window"]}))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    best = candidates[0][1]
    best["selection_rule"] = (
        "Smallest daytime complete fire+geo pair ≤80 MB preferring Aqua and cache hits; "
        "chosen before examining fire-mask outcomes."
    )
    return best


def main() -> None:
    freeze_daily_coverage_rule()
    auth = try_login()
    box = STUDY["bbox"]
    bbox = (box["west"], box["south"], box["east"], box["north"])
    windows = []
    # Train+validation windows only for pilot recovery (2023–2024). Keep 2025–2026 for later expansion.
    recover_windows = [w for w in DATE_WINDOWS if w[0][:4] in {"2023", "2024"}]
    for start, end in recover_windows:
        print(f"Searching {start} … {end}", flush=True)
        windows.append(inventory_window(start, end, bbox))

    pilot = choose_pilot(windows)
    free_bytes = None
    try:
        import shutil

        free_bytes = shutil.disk_usage(ROOT).free
    except Exception:
        pass

    smoke_2019 = {
        "label": "reader_smoke_test_only",
        "window": {"start": "2019-03-04", "end": "2019-03-10"},
        "note": (
            "March 2019 is outside the Maguindanao 2023–2026 training windows. "
            "Use only if explicitly labeled as a reader smoke test."
        ),
        "plan_ref": "data/metrics/mindanao_2019-03_download_plan.json",
    }

    payload = {
        "inventoried_at_utc": datetime.now(timezone.utc).isoformat(),
        "earthdata_login": bool(auth),
        "study": STUDY,
        "daily_coverage_rule_version": HOTSPOT_DAILY_COVERAGE_RULE["version"],
        "windows": [
            {k: v for k, v in w.items() if k != "objects_keyed"}
            for w in windows
        ],
        "totals": {
            "daytime_complete_pairs": sum(w["daytime_complete_pairs"] for w in windows),
            "estimated_daytime_transfer_bytes": sum(w["estimated_daytime_transfer_bytes"] for w in windows),
            "peak_disk_note": (
                "Peak disk ≈ existing raw/cache + largest concurrent batch. "
                f"Free bytes now: {free_bytes}."
            ),
            "free_bytes": free_bytes,
        },
        "pilot": pilot,
        "march_2019": smoke_2019,
    }
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    # Keep granule objects map separately? skip — re-search on process
    print(json.dumps({"pilot": pilot, "totals": payload["totals"]}, indent=2))


if __name__ == "__main__":
    main()
