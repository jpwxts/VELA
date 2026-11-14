"""Background refresh of Philippine FIRMS detections into the observation store.

Usage:
  python -m scripts.refresh_philippines_firms --once
  python -m scripts.refresh_philippines_firms --loop --interval-minutes 30

Requires FIRMS_MAP_KEY in .env. Closing the browser does not stop this process.
At Philippine midnight the worker advances Live to the new day automatically
because it always queries philippine_today().
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os

import httpx
from dotenv import load_dotenv

from app.db import ResponseCache
from app.firms import FirmsClient
from vela.boundaries import geometry_from_preset, point_in_geometry
from vela.firms_day import fetch_firms_for_ph_day, ph_day_for_utc
from vela.observation_store import ObservationStore, philippine_today
from vela.settings import DATA_DIR, ROOT, settings

load_dotenv(ROOT / ".env")


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


def _bbox_from_preset(preset_id: str) -> tuple[float, float, float, float]:
    from vela.boundaries import geometry_bbox

    return geometry_bbox(geometry_from_preset(preset_id))


def refresh_day(ph_day: str | None = None, *, store: ObservationStore | None = None) -> dict:
    firms = build_firms()
    if not firms.key:
        raise RuntimeError("FIRMS_MAP_KEY is not configured.")
    store = store or ObservationStore()
    day = ph_day or philippine_today().isoformat()
    # National multipolygon ring used only for FIRMS day fetch pad; clip afterward.
    from vela.boundaries import primary_ring_for_display

    ring = primary_ring_for_display(geometry_from_preset("philippines"))
    platforms = ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"]
    checked_at = datetime.now(timezone.utc).isoformat()
    payload = fetch_firms_for_ph_day(firms, ring, day, platforms, pad=0.05)
    geometry = geometry_from_preset("philippines")
    rows = []
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
            item["geometry_scope"] = "philippines"
            kept.append(item)
            rows.append(item)
        feed_status = "ok" if status == "ok" and kept else (
            "ok_zero" if status == "ok" else ("unavailable" if status == "product_unavailable" else "failed")
        )
        store.record_feed_check(
            ph_date=day,
            platform=platform,
            status=feed_status,
            count=len(kept),
            message=status,
            checked_at=checked_at,
        )
    written = store.upsert_detections(rows, retrieved_at=checked_at)
    store.set_checkpoint(
        "philippines_firms_refresh",
        {
            "ph_date": day,
            "written": written,
            "checked_at": checked_at,
            "total_count": payload.get("total_count"),
        },
    )
    return {
        "ph_date": day,
        "written": written,
        "checked_at": checked_at,
        "platforms": platforms,
        "store": str(store.path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run a single refresh and exit.")
    parser.add_argument("--loop", action="store_true", help="Refresh forever.")
    parser.add_argument("--interval-minutes", type=float, default=30.0)
    parser.add_argument("--ph-date", default=None, help="Override Philippine day (YYYY-MM-DD).")
    args = parser.parse_args()
    if not args.once and not args.loop:
        args.once = True
    while True:
        result = refresh_day(args.ph_date)
        print(json_dumps(result), flush=True)
        if args.once:
            break
        time.sleep(max(60.0, args.interval_minutes * 60.0))


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, sort_keys=True)


if __name__ == "__main__":
    main()
