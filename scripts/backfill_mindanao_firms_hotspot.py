"""Backfill compact Maguindanao FIRMS detections for hotspot-forecast training.

Inventory cached FIRMS first, estimate transfer, then fetch missing Philippine
days into data/observations/philippines.sqlite. Retains compact detections only.

Usage:
  python -m scripts.backfill_mindanao_firms_hotspot --plan
  python -m scripts.backfill_mindanao_firms_hotspot --run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import ResponseCache
from app.firms import FirmsClient
from vela.boundaries import geometry_from_preset, point_in_geometry
from vela.firms_day import fetch_firms_for_ph_day, ph_day_for_utc
from vela.hotspot_forecast import INVENTORY_PATH, STUDY, freeze_rules
from vela.observation_store import ObservationStore
from vela.settings import DATA_DIR, settings

load_dotenv(ROOT / ".env")

# Multi-season windows (Philippine local days to issue/label).
DATE_WINDOWS = [
    ("2023-02-15", "2023-03-14"),
    ("2023-08-01", "2023-08-28"),
    ("2024-02-15", "2024-03-14"),
    ("2024-08-01", "2024-08-28"),
    ("2025-02-15", "2025-03-07"),
    ("2026-11-01", "2026-11-14"),
]


def _daterange(start: str, end: str) -> list[date]:
    a = date.fromisoformat(start)
    b = date.fromisoformat(end)
    out = []
    cur = a
    while cur <= b:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def planned_days() -> list[date]:
    days: list[date] = []
    for start, end in DATE_WINDOWS:
        days.extend(_daterange(start, end))
    return sorted(set(days))


def _http_get(url: str) -> tuple[int, str]:
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        return response.status_code, response.text


def build_firms() -> FirmsClient:
    cfg = settings()
    return FirmsClient(
        os.environ.get("FIRMS_MAP_KEY", ""),
        ResponseCache(DATA_DIR / "cache" / "firms.sqlite"),
        _http_get,
        max_span=float(cfg["max_request_span_degrees"]),
        day_range=1,
    )


def inventory() -> dict:
    cache = DATA_DIR / "cache" / "firms.sqlite"
    store = ObservationStore()
    cache_bytes = cache.stat().st_size if cache.is_file() else 0
    store_bytes = store.path.stat().st_size if store.path.is_file() else 0
    days = planned_days()
    # Rough transfer estimate: ~80 KB CSV average per product-day × 4 products.
    estimate_bytes = len(days) * 4 * 80_000
    return {
        "study": STUDY,
        "windows": DATE_WINDOWS,
        "planned_ph_days": len(days),
        "cached_firms_sqlite_bytes": cache_bytes,
        "observation_store_bytes": store_bytes,
        "estimated_additional_transfer_bytes": estimate_bytes,
        "estimated_peak_disk_bytes": cache_bytes + store_bytes + estimate_bytes,
        "free_disk_note": "Keep under available free space; incremental fetch; compact cell-days retained after build.",
        "inventoried_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def backfill_day(firms: FirmsClient, store: ObservationStore, ph_day: date, geometry) -> dict:
    box = STUDY["bbox"]
    ring = [
        [box["west"], box["south"]],
        [box["east"], box["south"]],
        [box["east"], box["north"]],
        [box["west"], box["north"]],
        [box["west"], box["south"]],
    ]
    platforms = ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"]
    payload = fetch_firms_for_ph_day(firms, ring, ph_day.isoformat(), platforms, pad=0.02)
    checked_at = datetime.now(timezone.utc).isoformat()
    rows = []
    feed_ok = 0
    for result in payload.get("results") or []:
        platform = result.get("platform") or "Unrecognized"
        status = result.get("status") or "unknown"
        hotspots = result.get("hotspots") or []
        kept = []
        for spot in hotspots:
            try:
                lon = float(spot["lon"])
                lat = float(spot["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (
                box["west"] <= lon <= box["east"] and box["south"] <= lat <= box["north"]
            ):
                continue
            if not point_in_geometry(lon, lat, geometry):
                continue
            item = dict(spot)
            item["platform"] = spot.get("platform") or platform
            item["acq_date_ph"] = item.get("acq_date_ph") or ph_day_for_utc(
                str(item.get("acq_date") or ""), item.get("acq_time")
            )
            item["geometry_scope"] = "mindanao_hotspot_study"
            kept.append(item)
            rows.append(item)
        if status in {"ok", "no_hotspots"}:
            feed_ok += 1
        feed_status = (
            "ok"
            if status == "ok" and kept
            else "ok_zero"
            if status in {"ok", "no_hotspots"}
            else "unavailable"
            if status == "product_unavailable"
            else "failed"
        )
        store.record_feed_check(
            ph_date=ph_day.isoformat(),
            platform=platform,
            status=feed_status,
            count=len(kept),
            message=status,
            checked_at=checked_at,
        )
    written = store.upsert_detections(rows, retrieved_at=checked_at)
    regional_query_ok = feed_ok >= 2
    store.set_checkpoint(
        f"hotspot_backfill_{ph_day.isoformat()}",
        {
            "ph_date": ph_day.isoformat(),
            "written": written,
            "feed_ok": feed_ok,
            "regional_query_ok": regional_query_ok,
            "total_count": payload.get("total_count"),
            "checked_at": checked_at,
        },
    )
    return {
        "ph_date": ph_day.isoformat(),
        "written": written,
        "feed_ok": feed_ok,
        "regional_query_ok": regional_query_ok,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.4)
    args = parser.parse_args()
    freeze_rules()
    plan = inventory()
    INVENTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY_PATH.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.plan or not args.run:
        print(json.dumps(plan, indent=2))
        if not args.run:
            return
    if not os.environ.get("FIRMS_MAP_KEY", "").strip():
        raise SystemExit("FIRMS_MAP_KEY is required for --run")
    firms = build_firms()
    store = ObservationStore()
    geometry = geometry_from_preset("mindanao")
    results = []
    for day in planned_days():
        # Skip if checkpoint already ok
        existing = store.get_checkpoint(f"hotspot_backfill_{day.isoformat()}")
        if existing and existing.get("regional_query_ok"):
            results.append({"ph_date": day.isoformat(), "skipped": True, **existing})
            continue
        row = backfill_day(firms, store, day, geometry)
        results.append(row)
        print(json.dumps(row), flush=True)
        time.sleep(max(0.0, args.sleep_seconds))
    summary = {
        "days": len(results),
        "written_total": sum(int(r.get("written") or 0) for r in results),
        "ok_days": sum(1 for r in results if r.get("regional_query_ok") or r.get("skipped")),
        "inventory": plan,
    }
    (DATA_DIR / "metrics" / "philippines_hotspot_backfill.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
