"""Every hotspot keeps its own satellite reading and its own surface weather.

A drawn boundary used to report one weather point at its centre. Detection is
per pixel: each hotspot has its own brightness temperature, fire radiative power,
pass time and location, so each one must carry and show its own values.
"""

from __future__ import annotations

import json
from datetime import date

from app.firms import parse_hotspots
from vela.hotspot_conditions import (
    ARCHIVE_URL,
    FORECAST_URL,
    build_hotspot_conditions,
    pass_hour_utc,
)
from vela.land_check import classify_detections, normalize_ring

VIIRS_CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight\n"
    "7.38779,124.38444,341.2,0.39,0.36,2026-11-14,459,N20,VIIRS,n,2.0NRT,296.4,10.37,D\n"
    "7.13476,124.16110,318.9,0.41,0.37,2026-11-14,459,N20,VIIRS,h,2.0NRT,294.1,3.56,D\n"
)
MODIS_CSV = (
    "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_t31,frp,daynight\n"
    "8.1,125.2,322.5,1.1,1.0,2026-11-14,515,Aqua,MODIS,72,6.1NRT,298.7,14.2,D\n"
)


def test_parse_keeps_each_pixel_temperature_and_size():
    viirs = parse_hotspots(VIIRS_CSV)
    assert [row["brightness"] for row in viirs] == [341.2, 318.9]
    assert [row["bright_2"] for row in viirs] == [296.4, 294.1]
    assert viirs[0]["scan"] == 0.39 and viirs[0]["track"] == 0.36
    modis = parse_hotspots(MODIS_CSV)[0]
    assert modis["brightness"] == 322.5
    assert modis["bright_2"] == 298.7
    assert modis["instrument"] == "MODIS"


def test_land_check_rows_keep_every_hotspot_reading():
    ring = normalize_ring([[124.0, 7.0], [126.5, 7.0], [126.5, 9.0], [124.0, 9.0]])
    payload = {
        "results": [
            {
                "platform": "NOAA-20",
                "product": "VIIRS_NOAA20_NRT",
                "status": "ok",
                "coverage": "unknown",
                "hotspots": parse_hotspots(VIIRS_CSV),
            }
        ]
    }
    heat = classify_detections(payload, ring)
    rows = sorted(heat["inside"], key=lambda row: row["lat"])
    # Two different pixels, two different temperatures: never one shared value.
    assert [row["brightness"] for row in rows] == [318.9, 341.2]
    assert [row["frp"] for row in rows] == [3.56, 10.37]
    assert rows[0]["bright_2"] == 294.1
    assert rows[0]["daynight"] == "D"
    assert rows[0]["instrument"] == "VIIRS"
    assert rows[0]["scan"] == 0.41


def test_pass_hour_rounds_to_nearest_utc_hour():
    assert pass_hour_utc("2026-11-14", "04:59").isoformat() == "2026-11-14T05:00:00+00:00"
    assert pass_hour_utc("2026-11-14", "459").isoformat() == "2026-11-14T05:00:00+00:00"
    assert pass_hour_utc("2026-11-13", "16:28").isoformat() == "2026-11-13T16:00:00+00:00"
    # Rounding past midnight moves to the next UTC day.
    assert pass_hour_utc("2026-11-13", "23:40").isoformat() == "2026-11-14T00:00:00+00:00"
    assert pass_hour_utc("bad", "12:00") is None


def _open_meteo_reply(locations):
    """Multi-location Open-Meteo reply: one hourly series per requested point."""

    reply = []
    for lat, lon, temps in locations:
        reply.append(
            {
                "latitude": round(lat, 2),
                "longitude": round(lon, 2),
                "elevation": 120.0,
                "hourly": {
                    "time": [f"2026-11-14T{hour:02d}:00" for hour in range(24)],
                    "temperature_2m": temps,
                    "relative_humidity_2m": [60 + hour for hour in range(24)],
                    "wind_speed_10m": [5.0 + hour for hour in range(24)],
                    "wind_direction_10m": [90.0] * 24,
                    "precipitation": [0.0] * 24,
                },
            }
        )
    return reply


def test_each_hotspot_gets_weather_at_its_own_point_and_pass_hour():
    calls = []

    def getter(url, params):
        calls.append((url, params))
        lats = [float(value) for value in params["latitude"].split(",")]
        lons = [float(value) for value in params["longitude"].split(",")]
        # Each location gets a distinct temperature curve so a centre-point mix-up shows.
        locations = [
            (lat, lon, [20.0 + index * 5 + hour * 0.5 for hour in range(24)])
            for index, (lat, lon) in enumerate(zip(lats, lons))
        ]
        body = _open_meteo_reply(locations)
        return 200, json.dumps(body if len(body) > 1 else body[0]).encode()

    points = [
        {"id": "a", "lat": 7.38779, "lon": 124.38444, "acq_date": "2026-11-14", "acq_time": "04:59"},
        {"id": "b", "lat": 8.98123, "lon": 125.63084, "acq_date": "2026-11-14", "acq_time": "10:02"},
    ]
    result = build_hotspot_conditions(points, getter, today=date(2026, 11, 15))
    assert result["ok"] is True
    assert len(calls) == 1, "points on the same day share one batched request"
    url, params = calls[0]
    assert url == FORECAST_URL
    assert params["start_date"] == params["end_date"] == "2026-11-14"
    assert params["timezone"] == "GMT"
    by_id = {row["id"]: row for row in result["points"]}
    # Point a: location index 0, hour 05 -> 20 + 0 + 2.5
    assert by_id["a"]["status"] == "ok"
    assert by_id["a"]["valid_time_utc"] == "2026-11-14T05:00Z"
    assert by_id["a"]["air_temperature_c"] == 22.5
    assert by_id["a"]["relative_humidity_percent"] == 65
    assert by_id["a"]["wind_speed_km_h"] == 10.0
    assert by_id["a"]["wind_direction_text"] == "from the east"
    # Point b: location index 1, hour 10 -> 20 + 5 + 5.0
    assert by_id["b"]["air_temperature_c"] == 30.0
    assert by_id["a"]["air_temperature_c"] != by_id["b"]["air_temperature_c"]
    assert result["summary"]["air_temperature_c"] == {"min": 22.5, "max": 30.0, "mean": 26.2}


def test_old_dates_use_the_archive_and_failures_stay_per_point():
    def getter(url, params):
        assert url == ARCHIVE_URL
        return 503, b"busy"

    points = [{"id": 1, "lat": 7.0, "lon": 124.0, "acq_date": "2025-03-06", "acq_time": "05:30"}]
    result = build_hotspot_conditions(points, getter, today=date(2026, 11, 15))
    assert result["ok"] is False
    assert result["points"][0]["status"] == "unavailable"
    assert result["points"][0]["air_temperature_c"] is None


def test_unreadable_point_is_reported_not_guessed():
    result = build_hotspot_conditions(
        [{"id": "x", "lat": 7.0, "lon": 124.0, "acq_date": "", "acq_time": ""}],
        lambda url, params: (500, b""),
        today=date(2026, 11, 15),
    )
    assert result["points"][0]["status"] == "missing_time"


def test_history_heat_days_name_their_satellites():
    from vela.history import attach_heat_overlay

    payload = {"days": [{"date": "2026-11-02", "activity_status": "not_processed"}]}
    merged = attach_heat_overlay(
        payload,
        heat_days=[{"date": "2026-11-02", "count": 26, "area_count": 17,
                    "platforms": ["NOAA-21", "NOAA-20", "NOAA-20"], "queried": True}],
    )
    day = merged["days"][0]
    assert day["heat_count"] == 26
    assert day["heat_area_count"] == 17
    assert day["heat_platforms"] == ["NOAA-20", "NOAA-21"]
