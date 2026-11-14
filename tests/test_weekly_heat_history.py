"""Weekly heat history: PH days, snapshots, failures, and polygon clip."""

from __future__ import annotations

from vela.boundaries import geometry_from_preset, point_in_geometry
from vela.public_hotspots import load_geojson
from vela.weekly_heat_history import (
    build_weekly_heat_history,
    ph_day_for_utc,
    utc_dates_for_ph_day,
)


def test_one_day_snapshot_does_not_imply_full_week():
    history = build_weekly_heat_history(
        anchor_date="2026-11-07",
        preset_id="philippines",
        known_days=["2026-11-07"],
        fetch_missing=False,
    )
    assert history["week_start"] == "2026-11-02"
    assert history["week_end"] == "2026-11-08"
    assert "Available readings cover 7 November" in history["summary"]["lead"]
    assert history["summary"]["action"] == "check_rest"
    assert history["summary"]["unchecked_count"] == 6
    by_date = {day["date"]: day for day in history["days"]}
    assert by_date["2026-11-07"]["status"] == "heat_detected"
    assert by_date["2026-11-07"]["detection_count"] > 0
    # Other calendar days stay unchecked — a one-day snapshot is not a week search.
    for iso in ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]:
        assert by_date[iso]["status"] == "not_checked"
        assert by_date[iso]["detection_count"] == 0


def test_failed_feed_never_becomes_zero():
    class FailingFirms:
        def hotspots(self, *args, **kwargs):
            raise RuntimeError("FIRMS unavailable")

    # Empty square with no snapshot for this week → live path only.
    ring = [
        [120.0, 14.0],
        [120.01, 14.0],
        [120.01, 14.01],
        [120.0, 14.01],
        [120.0, 14.0],
    ]
    history = build_weekly_heat_history(
        anchor_date="2025-03-10",
        geometry={"type": "Polygon", "coordinates": [ring]},
        label="Tiny Luzon plot",
        known_days=[],
        fetch_missing=True,
        firms_client=FailingFirms(),
    )
    failed = [day for day in history["days"] if day["status"] == "request_failed"]
    assert failed
    for day in failed:
        assert day["detection_count"] == 0
        assert day["checked"] is False
        assert "not recorded as zero" in (day["message"] or "").lower() or "failed" in day["plain_status"].lower()
    assert history["summary"]["failed_count"] == len(failed)
    # Lead must not claim a completed no-heat week from failures.
    assert "of the" not in history["summary"]["lead"] or history["summary"]["checked_count"] == 0


def test_utc_reading_assigns_to_next_philippine_date():
    assert ph_day_for_utc("2026-11-07", "17:24") == "2026-11-08"
    assert ph_day_for_utc("2026-11-07", "05:10") == "2026-11-07"
    assert utc_dates_for_ph_day(__import__("datetime").date(2026, 11, 8)) == [
        "2026-11-07",
        "2026-11-08",
    ]
    collection = load_geojson("2026-11-07")
    late = [
        feature
        for feature in collection["features"]
        if str(feature["properties"]["acq_date_ph"]) == "2026-11-08"
    ]
    assert late
    history = build_weekly_heat_history(
        anchor_date="2026-11-07",
        preset_id="philippines",
        fetch_missing=False,
    )
    by_date = {day["date"]: day for day in history["days"]}
    # Spill detections may appear on 8 Nov without marking that day as a full search.
    if by_date["2026-11-08"]["detection_count"]:
        assert by_date["2026-11-08"]["status"] == "heat_detected"
        assert by_date["2026-11-08"]["checked"] is False
        assert by_date["2026-11-08"]["has_heat"] is True
    assert by_date["2026-11-07"]["checked"] is True


def test_point_outside_mindanao_boundary_is_clipped_out():
    mindanao = geometry_from_preset("mindanao")
    # Masbate-ish coordinate from the national snapshot, north of Mindanao.
    lon, lat = 123.75, 12.05
    assert not point_in_geometry(lon, lat, mindanao)

    ph = build_weekly_heat_history(
        anchor_date="2026-11-07",
        preset_id="philippines",
        fetch_missing=False,
    )
    mind = build_weekly_heat_history(
        anchor_date="2026-11-07",
        preset_id="mindanao",
        fetch_missing=False,
    )
    ph_day = next(day for day in ph["days"] if day["date"] == "2026-11-07")
    mind_day = next(day for day in mind["days"] if day["date"] == "2026-11-07")
    assert ph_day["detection_count"] > mind_day["detection_count"]
    assert mind_day["detection_count"] == 12 or mind_day["detection_count"] <= ph_day["detection_count"]

    # Drawn plot entirely outside Mindanao (Luzon) must not inherit Mindanao heat.
    luzon_ring = [
        [120.9, 14.5],
        [121.1, 14.5],
        [121.1, 14.7],
        [120.9, 14.7],
        [120.9, 14.5],
    ]
    outside = build_weekly_heat_history(
        anchor_date="2026-11-07",
        geometry={"type": "Polygon", "coordinates": [luzon_ring]},
        label="Metro Manila plot",
        known_days=["2026-11-07"],
        fetch_missing=False,
    )
    outside_day = next(day for day in outside["days"] if day["date"] == "2026-11-07")
    # Snapshot is clipped to the drawn polygon; Manila plot has no Nov 7 snapshot points.
    assert outside_day["detection_count"] == 0
    assert outside_day["status"] in {"no_readings", "not_checked"}
