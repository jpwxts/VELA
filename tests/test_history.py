"""Monthly history preserves the coverage and hold-out rules of weekly history."""

from datetime import date

import pandas as pd
import pytest

from vela import serving
from vela.history import build_monthly_history


RING = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]


def rows(day, count, active=0, **updates):
    return [{
        "cell_id": f"{index}:1", "local_date": day,
        "center_lon": 0.25, "center_lat": 0.25,
        "modis_detected": index < active, "modis_visible_km2": 20,
        "viirs_visible_km2": 15, "shared_visible_km2": 15,
        "viirs_hotspot_pixel_count": 0, "hours_from_aqua": 0.2,
        **updates,
    } for index in range(count)]


def stored(monkeypatch, records):
    frame = pd.DataFrame(records)
    monkeypatch.setattr(serving, "_frame", lambda path: frame if path == serving.PAIRED_PATH else pd.DataFrame())
    monkeypatch.setattr(serving, "model_status", lambda: {"ready": False})
    monkeypatch.setattr(serving, "selected_method", lambda: None)
    monkeypatch.setattr(serving, "region_label", lambda *args: {"code": "represented_in_training"})


def test_month_weights_daily_rates_by_estimated_cells_and_keeps_missing_days(monkeypatch):
    stored(monkeypatch, rows("2021-07-19", 10, 2) + rows("2021-07-20", 30, 12))
    result = build_monthly_history(RING, 2021, 7)
    days = {entry["date"]: entry for entry in result["days"]}
    assert len(days) == 31
    assert days["2021-07-19"]["activity_rate"] == pytest.approx(0.2)
    assert days["2021-07-20"]["activity_rate"] == pytest.approx(0.4)
    assert days["2021-07-21"]["activity_rate"] is None
    assert days["2021-07-21"]["activity_status"] == "not_processed"
    assert result["summary"]["activity_rate"] == pytest.approx(14 / 40)
    assert result["summary"]["days_with_estimates"] == 2
    assert result["summary"]["activity_status"] == "partial"
    assert len(result["months"]) == 12
    assert result["months"][5]["activity_rate"] is None


def test_observed_zero_is_not_a_gap_and_duplicate_passes_count_once(monkeypatch):
    records = rows("2021-07-19", 20)
    records.append({**records[0], "modis_detected": True, "modis_visible_km2": 15})
    stored(monkeypatch, records)
    result = build_monthly_history(RING, 2021, 7)
    day = result["days"][18]
    assert day["activity_rate"] == 0
    assert day["clear_zero"] is True
    assert day["activity_denominator"] == 20
    assert result["days"][19]["activity_rate"] is None


def test_picker_years_before_records_are_missing_and_leap_days_are_preserved(monkeypatch):
    stored(monkeypatch, rows("2021-07-19", 20, 5))
    result = build_monthly_history(RING, 1990, 1)
    assert len(result["days"]) == 31
    assert all(entry["activity_rate"] is None for entry in result["days"])
    assert result["status"] == "not_processed"
    assert result["available_months"] == ["2021-07"]
    assert len(build_monthly_history(RING, 1992, 2)["days"]) == 29


def test_monthly_and_annual_outputs_do_not_reveal_reserved_validation_values(monkeypatch):
    stored(monkeypatch, rows("2023-07-17", 20, 20))
    result = build_monthly_history(RING, 2023, 7)
    assert result["days"][16]["activity_status"] == "hidden"
    assert result["days"][16]["activity_rate"] is None
    assert result["days"][16]["activity_denominator"] is None
    assert result["summary"]["activity_rate"] is None
    assert all(entry["activity_rate"] is None for entry in result["months"])


def test_sparse_weeks_keep_daily_values_unavailable(monkeypatch):
    stored(monkeypatch, rows("2021-07-19", 1, 1))
    result = build_monthly_history(RING, 2021, 7)
    assert result["days"][18]["activity_status"] == "insufficient"
    assert result["days"][18]["activity_rate"] is None


def test_pending_noaa_cells_make_the_day_partial_without_becoming_zeros(monkeypatch):
    records = rows("2021-07-19", 20, 20)
    records += [{**item, "cell_id": f"pending-{index}", "modis_visible_km2": 0,
                 "viirs_platform": "NOAA-20"}
                for index, item in enumerate(rows("2021-07-19", 5))]
    stored(monkeypatch, records)
    result = build_monthly_history(RING, 2021, 7)
    day = result["days"][18]
    assert day["activity_status"] == "partial"
    assert day["eligible_cell_days"] == 25
    assert day["activity_denominator"] == 20
    assert day["activity_rate"] == 1


def test_january_uses_the_whole_week_when_coverage_spans_new_year(monkeypatch):
    stored(monkeypatch, rows("2020-12-31", 20) + rows("2021-01-01", 2, 2))
    result = build_monthly_history(RING, 2021, 1)
    assert result["days"][0]["activity_rate"] == 1
    assert result["summary"]["activity_denominator"] == 2


def test_cells_outside_the_drawn_polygon_do_not_enter_the_history(monkeypatch):
    records = rows("2021-07-19", 20)
    records += rows("2021-07-19", 20, 20, center_lon=0.8, center_lat=0.8)
    stored(monkeypatch, records)
    triangle = [[0, 0], [1, 0], [0, 1], [0, 0]]
    result = build_monthly_history(triangle, 2021, 7)
    assert result["summary"]["activity_rate"] == 0
    assert result["summary"]["activity_denominator"] == 20


def test_future_dates_are_not_published_even_if_rows_exist(monkeypatch):
    stored(monkeypatch, rows("2021-07-19", 20, 5) + rows("2021-07-21", 20, 20))
    result = build_monthly_history(RING, 2021, 7, today=date(2021, 7, 20))
    assert result["days"][20]["activity_status"] == "future"
    assert result["days"][20]["activity_rate"] is None
    assert result["last_observation"] == "2021-07-19"


def test_history_endpoint_validates_dates_and_normalizes_the_boundary(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    calls = []
    monkeypatch.setattr(main, "build_monthly_history", lambda *args, **kwargs: calls.append(args) or {"status": "ok"})
    client = TestClient(main.app)
    payload = {"coordinates": RING[:-1], "year": 1990, "month": 1}
    assert client.post("/api/history/month", json=payload).status_code == 200
    assert calls[0] == (RING, 1990, 1)
    assert client.post("/api/history/month", json={**payload, "year": 1989}).status_code == 422
    assert client.post("/api/history/month", json={**payload, "month": 13}).status_code == 422
    assert client.post("/api/history/month", json={**payload, "coordinates": [[0, 0], [200, 0], [0, 1]]}).status_code == 400
