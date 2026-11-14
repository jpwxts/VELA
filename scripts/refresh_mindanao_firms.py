"""Refresh Mindanao FIRMS detections into the observation store every 4 hours.

Usage:
  python -m scripts.refresh_mindanao_firms --once
  python -m scripts.refresh_mindanao_firms --loop --interval-minutes 240

Requires FIRMS_MAP_KEY in .env. Writes data/metrics/mindanao_firms_refresh_status.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from dotenv import load_dotenv

from app.db import ResponseCache
from app.firms import FirmsClient
from vela.boundaries import geometry_bbox, geometry_from_preset, point_in_geometry, primary_ring_for_display
from vela.firms_day import fetch_firms_for_ph_day, ph_day_for_utc
from vela.observation_store import ObservationStore, philippine_today
from vela.settings import DATA_DIR, ROOT as VELA_ROOT, settings

load_dotenv(VELA_ROOT / ".env")

STATUS_PATH = DATA_DIR / "metrics" / "mindanao_firms_refresh_status.json"
DEFAULT_INTERVAL_MINUTES = 240.0


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


def write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def refresh_mindanao_day(ph_day: str | None = None, *, store: ObservationStore | None = None) -> dict:
    firms = build_firms()
    if not firms.key:
        raise RuntimeError("FIRMS_MAP_KEY is not configured.")
    store = store or ObservationStore()
    day = ph_day or philippine_today().isoformat()
    geometry = geometry_from_preset("mindanao")
    ring = primary_ring_for_display(geometry)
    platforms = ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"]
    checked_at = datetime.now(timezone.utc).isoformat()
    payload = fetch_firms_for_ph_day(firms, ring, day, platforms, pad=0.05)
    rows = []
    platform_counts: dict[str, int] = {}
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
            if not point_in_geometry(lon, lat, geometry):
                continue
            item = dict(spot)
            item["platform"] = spot.get("platform") or platform
            item["acq_date_ph"] = item.get("acq_date_ph") or ph_day_for_utc(
                str(item.get("acq_date") or ""), item.get("acq_time")
            )
            item["geometry_scope"] = "mindanao"
            kept.append(item)
            rows.append(item)
        feed_status = (
            "ok"
            if status == "ok" and kept
            else (
                "ok_zero"
                if status == "ok"
                else ("unavailable" if status == "product_unavailable" else "failed")
            )
        )
        platform_counts[platform] = len(kept)
        store.record_feed_check(
            ph_date=day,
            platform=f"Mindanao-{platform}",
            status=feed_status,
            count=len(kept),
            message=status,
            checked_at=checked_at,
        )
    written = store.upsert_detections(rows, retrieved_at=checked_at)
    bbox = geometry_bbox(geometry)
    result = {
        "scope": "mindanao",
        "ph_date": day,
        "written": written,
        "detection_count": len(rows),
        "checked_at": checked_at,
        "platforms": platforms,
        "platform_counts": platform_counts,
        "bbox": {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]},
        "interval_minutes_default": DEFAULT_INTERVAL_MINUTES,
        "store": str(store.path),
        "ok": True,
        "error": None,
    }
    store.set_checkpoint("mindanao_firms_refresh", result)
    write_status(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run a single refresh and exit.")
    parser.add_argument("--loop", action="store_true", help="Refresh forever.")
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=DEFAULT_INTERVAL_MINUTES,
        help="Loop sleep between refreshes (default 240 = 4 hours).",
    )
    parser.add_argument("--ph-date", default=None, help="Override Philippine day (YYYY-MM-DD).")
    args = parser.parse_args()
    if not args.once and not args.loop:
        args.once = True
    while True:
        try:
            result = refresh_mindanao_day(args.ph_date)
            print(json.dumps(result, sort_keys=True), flush=True)
        except Exception as exc:  # noqa: BLE001
            failure = {
                "scope": "mindanao",
                "ok": False,
                "error": str(exc),
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "interval_minutes_default": DEFAULT_INTERVAL_MINUTES,
            }
            write_status(failure)
            print(json.dumps(failure, sort_keys=True), flush=True)
            if args.once:
                raise
        if args.once:
            break
        time.sleep(max(60.0, float(args.interval_minutes) * 60.0))


if __name__ == "__main__":
    main()
