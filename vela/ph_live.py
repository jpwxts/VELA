"""Philippine Live mode helpers: today, timestamps, and snapshot seeding."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from vela.firms_day import ph_day_for_utc
from vela.observation_store import ObservationStore, philippine_today
from vela.public_hotspots import feature_to_hotspot, load_geojson


def live_clock() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    ph = philippine_today(now)
    return {
        "utc_now": now.isoformat(),
        "ph_today": ph.isoformat(),
        "timezone": "Asia/Manila",
    }


def seed_public_snapshot(store: ObservationStore | None = None, day: str = "2026-11-07") -> dict:
    store = store or ObservationStore()
    collection = load_geojson(day)
    rows = []
    for feature in collection.get("features") or []:
        spot = feature_to_hotspot(feature)
        props = feature.get("properties") or {}
        spot["acq_date_ph"] = props.get("acq_date_ph") or ph_day_for_utc(
            str(spot.get("acq_date") or day), spot.get("acq_time")
        )
        spot["geometry_scope"] = "philippines"
        spot["source"] = "public_snapshot"
        rows.append(spot)
    written = store.upsert_detections(rows, retrieved_at=datetime.now(timezone.utc).isoformat())
    for platform in sorted({row.get("platform") for row in rows if row.get("platform")}):
        count = sum(1 for row in rows if row.get("platform") == platform)
        store.record_feed_check(
            ph_date=day,
            platform=str(platform),
            status="ok" if count else "ok_zero",
            count=count,
            message="seeded_from_public_snapshot",
        )
    # Also seed PH-local dates that fall on Nov 8 for late UTC passes.
    store.set_checkpoint("seed_public_snapshot", {"day": day, "written": written})
    return {"day": day, "written": written}


def persist_hotspot_payload(payload: dict, *, ph_date: str, store: ObservationStore | None = None) -> dict:
    store = store or ObservationStore()
    checked_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for result in payload.get("results") or []:
        platform = result.get("platform") or "Unrecognized"
        status = result.get("status") or "unknown"
        hotspots = result.get("hotspots") or []
        for spot in hotspots:
            item = dict(spot)
            item.setdefault("platform", platform)
            item["acq_date_ph"] = item.get("acq_date_ph") or ph_day_for_utc(
                str(item.get("acq_date") or ph_date), item.get("acq_time")
            )
            item["geometry_scope"] = "philippines"
            rows.append(item)
        feed_status = (
            "ok"
            if status == "ok" and hotspots
            else "ok_zero"
            if status == "ok"
            else "unavailable"
            if status == "product_unavailable"
            else "failed"
        )
        store.record_feed_check(
            ph_date=ph_date,
            platform=platform,
            status=feed_status,
            count=len(hotspots),
            message=status,
            checked_at=checked_at,
        )
    written = store.upsert_detections(rows, retrieved_at=checked_at)
    return {
        "written": written,
        "checked_at": checked_at,
        "latest_observation_at": store.latest_detection_time(),
        "latest_successful_check": store.latest_successful_check(),
    }


def timestamps_block(store: ObservationStore | None = None, activity: dict | None = None) -> dict:
    store = store or ObservationStore()
    check = store.latest_successful_check()
    return {
        "latest_satellite_observation_at": store.latest_detection_time(),
        "last_successful_source_check_at": None if check is None else check.get("checked_at"),
        "estimates_processed_through": None if not activity else activity.get("processed_at"),
        "note": (
            "Observation time, retrieval time, and model-processing time stay distinct. "
            "A failed feed keeps the last successful result with its original timestamp."
        ),
    }
