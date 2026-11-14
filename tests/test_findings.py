"""Selected-location findings: VPD math, Zambia RF cell-day, weather gaps."""

from __future__ import annotations

from vela.findings import ZAMBIA_CELL_ID, ZAMBIA_DATE, build_findings, reliability_block
from vela.meteomatics import vapour_pressure_deficit_kpa, weather_from_values


def test_vpd_at_32c_and_50_percent_humidity():
    result = vapour_pressure_deficit_kpa(32.0, 50.0)
    assert result["status"] == "ok"
    assert result["vpd_kPa"] == 2.38


def test_vpd_at_100_percent_humidity_is_zero():
    result = vapour_pressure_deficit_kpa(20.0, 100.0)
    assert result["status"] == "ok"
    assert result["vpd_kPa"] == 0.0


def test_missing_humidity_keeps_temperature_and_marks_vpd_unavailable():
    weather = weather_from_values(
        latitude=-15.16,
        longitude=27.13,
        valid_time="2021-07-22T12:00:00Z",
        temperature_c=32.0,
        relative_humidity_percent=None,
        fixture=True,
    )
    assert weather["temperature_c"]["value"] == 32.0
    assert weather["temperature_c"]["status"] == "ok"
    assert weather["relative_humidity_percent"]["status"] == "missing"
    assert weather["air_dryness"]["status"] == "unavailable"
    assert weather["air_dryness"]["vpd_kPa"] is None


def test_zambia_fixture_keeps_zero_fire_pixels_distinct_from_rf_probability():
    payload = build_findings(
        scope="square",
        observation_date=ZAMBIA_DATE,
        place_name="Zambia woodland",
        cell_id=ZAMBIA_CELL_ID,
        platforms=[{"name": "Suomi-NPP", "time_utc": "11:00"}],
        empty=True,
        weather_fixture={
            "valid_time": f"{ZAMBIA_DATE}T12:00:00Z",
            "temperature_c": 32.0,
            "relative_humidity_percent": 50.0,
            "kind": "historical",
        },
    )
    model = payload["model"]
    assert model["status"] == "estimated_suomi"
    assert model["label"] == "Estimated from Suomi-NPP"
    assert model["raw_activity"] == 0.0
    assert model["hotspot_pixel_count"] == 0
    assert abs(model["model_probability"] - 0.010412366436853273) < 1e-9
    assert model["model_probability"] != model["raw_activity"]
    assert payload["weather"]["fixture"] is True
    assert payload["weather"]["air_dryness"]["vpd_kPa"] == 2.38


def test_reliability_matches_project_record_plain_language():
    block = reliability_block()
    assert block["matches_project_record"] is True
    assert block["value_percentage_points"] == 0.66
    assert "0.66 percentage points" in block["plain_language"]
    assert "wildfire" not in block["note"].lower() or "not a wildfire" in block["note"].lower()
