"""Preparedness forecasts stay separate from harmonization scores."""

from __future__ import annotations

import json
import struct

from vela.forecast_store import ForecastArchive
from vela.geotiff import read_center_value
from vela.preparedness import (
    build_day_outlook,
    build_forecast,
    parse_day_outlook,
    explain_day,
    parse_weather,
    verification_status,
)


def _weather_payload():
    past = ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09"]
    future = ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16"]
    times = past + future
    return {
        "latitude": 38.72,
        "longitude": -9.14,
        "timezone": "Europe/Lisbon",
        "daily": {
            "time": times,
            "temperature_2m_max": [20] * 7 + [18, 19, None, 17, 18, 19, 20],
            "relative_humidity_2m_min": [40] * 14,
            "wind_speed_10m_max": [3] * 14,
            "wind_gusts_10m_max": [6] * 14,
            "precipitation_sum": [0, 0, 0, 1, 2, 0, 0] + [0, 5, 0, 1, 0, 0, 0],
        },
    }


def test_recent_rain_stays_separate_from_forecast_rain():
    parsed = parse_weather(_weather_payload())
    assert parsed["recent_rain"]["millimetres"] == 3
    assert parsed["recent_rain"]["end"] == "2026-11-09"
    assert parsed["forecast_rain"]["millimetres"] == 6
    assert parsed["days"][0]["forecast_rain_mm"]["value"] == 0
    assert parsed["days"][0]["forecast_rain_mm"]["status"] == "quiet"
    assert parsed["days"][0]["lead_days"] == 0
    assert parsed["days"][2]["temperature_max_c"]["status"] == "missing"
    assert "wildfire" not in explain_day({**parsed["days"][1], "fire_danger": {"status": "unavailable"}}).lower()


def test_zero_rain_is_quiet_and_a_gap_is_missing():
    payload = _weather_payload()
    payload["daily"]["precipitation_sum"] = [0] * 14
    quiet = parse_weather(payload)
    assert quiet["recent_rain"]["status"] == "quiet"
    assert quiet["forecast_rain"]["status"] == "quiet"
    payload["daily"]["precipitation_sum"][0] = None
    missing = parse_weather(payload)
    assert missing["recent_rain"]["status"] == "missing"
    assert missing["recent_rain"]["millimetres"] is None


def test_center_geotiff_value_is_the_middle_sample():
    values = [1, 2, 3, 4, 12.5, 6, 7, 8, 9]
    blob = struct.pack("<9f", *values)
    payload = bytearray(b"II*\x00" + struct.pack("<I", 8))
    entries = [
        (256, 3, 1, 3),
        (257, 3, 1, 3),
        (258, 3, 1, 32),
        (259, 3, 1, 1),
        (277, 3, 1, 1),
        (339, 3, 1, 3),
        (273, 4, 1, 200),
        (279, 4, 1, len(blob)),
    ]
    payload += struct.pack("<H", len(entries))
    for tag in entries:
        payload += struct.pack("<HHII", *tag)
    payload.extend(b"\x00" * (200 - len(payload)))
    payload.extend(blob)
    assert read_center_value(bytes(payload)) == 12.5
    assert read_center_value(b"not a tiff") is None


def test_missing_fwi_feed_leaves_weather_in_place():
    def getter(url, params):
        if "open-meteo" in url:
            return 200, json.dumps(_weather_payload()).encode("utf-8")
        return 503, b"unavailable"

    forecast = build_forecast(-9.2, 38.6, -9.0, 38.8, getter, {"validation": {}})
    assert forecast["ok"] is True
    assert forecast["days"][1]["fire_danger"]["status"] == "unavailable"
    assert forecast["days"][1]["fire_danger"]["fwi"] is None
    assert forecast["performance"]["status"] == "pending_verification"
    assert forecast["recent_rain"]["millimetres"] == 3


def test_weather_connection_failure_returns_an_unavailable_forecast():
    def getter(_url, _params):
        raise OSError("offline")

    forecast = build_forecast(124.2, 7.0, 124.4, 7.2, getter, {"validation": {}})

    assert forecast["ok"] is False
    assert forecast["days"] == []
    assert forecast["message"] == "The weather feed is temporarily unavailable."


def test_held_out_error_stays_pending_until_a_validation_score_exists():
    pending = verification_status({"validation": "pending", "chosen_model": None})
    assert pending["status"] == "pending_verification"
    assert pending["held_out_error_percentage_points"] is None
    measured = verification_status(
        {"chosen_model": "raw_viirs", "validation": {"raw_viirs": {"weekly_mae_percentage_points": 1.5}}}
    )
    assert measured["held_out_error_percentage_points"] == 1.5


def test_an_issued_forecast_is_kept_and_a_second_brief_is_suppressed(tmp_path, monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import main

    archive = ForecastArchive(tmp_path / "forecasts.sqlite")
    forecast = build_forecast(
        0,
        0,
        1,
        1,
        lambda url, params: (200, json.dumps(_weather_payload()).encode("utf-8"))
        if "open-meteo" in url
        else (503, b""),
        {},
    )
    stored = archive.put_if_absent(forecast["issue_id"], forecast["region_key"], forecast)
    again = archive.put_if_absent(forecast["issue_id"], forecast["region_key"], forecast)
    assert again["issued_at"] == stored["issued_at"]
    assert stored["days"][0]["verification_status"] == "pending"
    monkeypatch.setattr(main, "ARCHIVE", archive)
    sent = []
    monkeypatch.setattr(
        main,
        "send_test_brief",
        lambda subject, body: sent.append(subject) or {"sent": True, "status": "sent", "message": "Sent to the test inbox."},
    )
    monkeypatch.setattr(
        main,
        "_latest_hotspots",
        lambda *args: {"observation_status": "no_hotspots", "date": "2026-11-10", "total_count": 0, "results": [], "message": "No hotspots returned."},
    )
    client = TestClient(main.app)
    body = {
        "west": 0,
        "south": 0,
        "east": 1,
        "north": 1,
        "issue_id": stored["issue_id"],
        "valid_date": stored["days"][0]["valid_date"],
        "confirm": True,
    }
    first = client.post("/api/preparedness/brief", json=body)
    second = client.post("/api/preparedness/brief", json=body)
    assert first.json()["sent"] is True
    assert second.json()["status"] == "duplicate"
    assert len(sent) == 1
    page = client.get("/")
    assert "Check my land" in page.text
    assert "Competition example" in page.text
def _hourly_payload():
    hours = [f"2026-11-14T{hour:02d}:00" for hour in range(24)]
    return {
        "latitude": 11.2,
        "longitude": 122.5,
        "timezone": "Asia/Manila",
        "current": {"time": "2026-11-14T13:15", "temperature_2m": 30.1},
        "hourly": {
            "time": hours,
            "temperature_2m": [24 + hour / 4 for hour in range(24)],
            "wind_speed_10m": [10] * 12 + [None] + [14] * 11,
            "weather_code": [2] * 24,
            "is_day": [0] * 6 + [1] * 12 + [0] * 6,
        },
    }


def test_day_outlook_keeps_three_hour_slots_and_marks_missing_values():
    outlook = parse_day_outlook(_hourly_payload())
    assert outlook["ok"] is True
    assert [slot["hour"] for slot in outlook["slots"]] == [0, 3, 6, 9, 12, 15, 18, 21]
    noon = outlook["slots"][4]
    assert noon["temperature_c"] == 27.0
    # A value the provider left out is missing, never zero.
    assert noon["wind_speed_km_h"] is None
    assert noon["is_day"] is True and outlook["slots"][0]["is_day"] is False
    assert outlook["now"] == "2026-11-14T13:15"
    assert outlook["timezone"] == "Asia/Manila"


def test_day_outlook_reports_a_failed_request_instead_of_raising():
    def refused(url, params=None):
        raise OSError("network unreachable")

    outlook = build_day_outlook(11.2, 122.5, refused)
    assert outlook["ok"] is False
    assert outlook["slots"] == []
    assert "could not be loaded" in outlook["message"]


def test_day_outlook_endpoint_validates_the_point_and_returns_local_slots(monkeypatch):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import main

    calls = []

    def hourly_getter(url, params=None):
        calls.append((url, params))
        return 200, json.dumps(_hourly_payload()).encode("utf-8")

    monkeypatch.setattr(main, "request_bytes", hourly_getter)
    client = TestClient(main.app)
    response = client.get("/api/day-outlook?lat=11.2&lon=122.5")

    assert response.status_code == 200
    assert response.json()["slots"][4]["wind_speed_km_h"] is None
    assert calls[0][1]["timezone"] == "auto"
    assert calls[0][1]["wind_speed_unit"] == "kmh"
    assert client.get("/api/day-outlook?lat=91&lon=122.5").status_code == 422
