"""Regression: land summary weather and heat stay independent of model estimate."""

from __future__ import annotations

from copy import deepcopy

from vela.firms_day import ph_day_for_utc, utc_dates_for_ph_day
from vela.land_check import annotate_forecast_days, build_land_check, normalize_ring


def _low_forecast():
    return {
        "ok": True,
        "point": {
            "latitude": 10.66,
            "longitude": 123.03,
            "timezone": "Asia/Manila",
            "label": "Weather near the center of your selection.",
        },
        "days": [
            {
                "valid_date": "2026-11-14",
                "fire_danger": {
                    "status": "measured",
                    "fwi": 5.0,
                    "ranking": None,
                    "source": "Copernicus Emergency Management Service, GWIS test.",
                },
                "temperature_max_c": {"status": "ok", "value": 30},
                "relative_humidity_min_percent": {"status": "ok", "value": 60},
                "forecast_rain_mm": {"status": "quiet", "value": 0},
                "wind_speed_max_m_s": {"status": "ok", "value": 3},
            },
            {
                "valid_date": "2026-11-15",
                "fire_danger": {"status": "measured", "fwi": 4.0, "ranking": None},
                "temperature_max_c": {"status": "ok", "value": 29},
                "relative_humidity_min_percent": {"status": "ok", "value": 62},
                "forecast_rain_mm": {"status": "quiet", "value": 0},
                "wind_speed_max_m_s": {"status": "ok", "value": 2},
            },
        ],
    }


def _ring_ph():
    return normalize_ring([[122.98, 10.62], [123.08, 10.62], [123.08, 10.70], [122.98, 10.70]])


def test_low_weather_with_missing_satellite_estimate():
    payload = build_land_check(
        ring=_ring_ph(),
        forecast=_low_forecast(),
        hotspot_payload={"results": [], "combined": {"coverage": "unknown"}},
        observation_date="2026-11-07",
    )
    assert payload["forecast"]["headline"] == "Low throughout the available forecast"
    assert payload["forecast"]["attention_day"] is None
    assert payload["forecast"]["days"][0]["danger_level"] == "Low"
    assert payload["activity"]["activity_rate"] is None
    assert payload["reliability"]["value_percentage_points"] == 0.66
    assert "Philippine" in payload["reliability"]["philippine_status"]
    assert payload["heat"]["inside_count"] == 0


def test_heat_detection_survives_missing_estimate():
    hotspots = {
        "combined": {"coverage": "observed"},
        "results": [
            {
                "platform": "NOAA-21",
                "status": "ok",
                "coverage": "observed",
                "hotspots": [
                    {
                        "lat": 10.65,
                        "lon": 123.03,
                        "platform": "NOAA-21",
                        "acq_date": "2026-11-07",
                        "acq_time": "04:33",
                        "acq_date_ph": "2026-11-07",
                        "acq_time_ph": "12:33",
                    }
                ],
            }
        ],
    }
    payload = build_land_check(
        ring=_ring_ph(),
        forecast={"ok": False, "days": [], "point": {}},
        hotspot_payload=hotspots,
        observation_date="2026-11-07",
    )
    assert payload["heat"]["inside_count"] == 1
    assert payload["heat"]["inside"][0]["platform"] == "NOAA-21"
    assert payload["activity"]["activity_rate"] is None
    assert payload["forecast"]["ok"] is False


def test_two_polygons_do_not_share_forecast_payload():
    first = build_land_check(
        ring=_ring_ph(),
        forecast=_low_forecast(),
        hotspot_payload={"results": [], "combined": {"coverage": "unknown"}},
        observation_date="2026-11-07",
        label="First plot",
    )
    second_forecast = deepcopy(_low_forecast())
    second_forecast["days"][0]["fire_danger"]["fwi"] = 40.0
    second = build_land_check(
        ring=normalize_ring([[124.0, 7.0], [124.1, 7.0], [124.1, 7.1], [124.0, 7.1]]),
        forecast=second_forecast,
        hotspot_payload={"results": [], "combined": {"coverage": "unknown"}},
        observation_date="2026-11-07",
        label="Second plot",
    )
    assert first["label"] == "First plot"
    assert second["label"] == "Second plot"
    assert first["forecast"]["days"][0]["danger_level"] == "Low"
    assert second["forecast"]["days"][0]["danger_level"] == "Very High"
    assert first["center"] != second["center"]


def test_philippine_date_crosses_utc_midnight():
    from datetime import date

    # 16:30 UTC on 7 Nov is already 00:30 on 8 Nov in Asia/Manila.
    assert ph_day_for_utc("2026-11-07", "16:30") == "2026-11-08"
    assert ph_day_for_utc("2026-11-07", "04:33") == "2026-11-07"
    utc_days = utc_dates_for_ph_day(date.fromisoformat("2026-11-08"))
    assert "2026-11-07" in utc_days
    assert "2026-11-08" in utc_days


def test_merge_preserves_cache_hits_across_utc_days():
    from vela.firms_day import merge_hotspot_payloads

    merged = merge_hotspot_payloads(
        [
            {
                "configured": True,
                "date": "2026-11-13",
                "results": [
                    {
                        "platform": "Aqua",
                        "status": "no_hotspots",
                        "product": "MODIS_NRT",
                        "processing": "near_real_time",
                        "cached": True,
                        "count": 0,
                        "hotspots": [],
                    }
                ],
            },
            {
                "configured": True,
                "date": "2026-11-14",
                "results": [
                    {
                        "platform": "Aqua",
                        "status": "no_hotspots",
                        "product": "MODIS_NRT",
                        "processing": "near_real_time",
                        "cached": True,
                        "count": 0,
                        "hotspots": [],
                    }
                ],
            },
        ],
        observation_date="2026-11-14",
    )
    aqua = next(row for row in merged["results"] if row["platform"] == "Aqua")
    assert aqua["cached"] is True
    assert aqua["status"] == "no_hotspots"


def test_select_one_allows_aqua_alone_without_suomi_pair():
    from vela.contributions import select_one

    chosen = select_one(
        [
            {
                "platform": "Aqua",
                "eligible": True,
                "detected": False,
                "visible_km2": 20,
                "hours_from_aqua": 0,
                "cell_id": "2393:174",
                "local_date": "2019-03-06",
            }
        ]
    )
    assert chosen is not None
    assert chosen["platform"] == "Aqua"
    assert chosen["rule"] == "aqua_when_eligible"


def test_land_and_weather_share_annotated_forecast_fields():
    annotated = annotate_forecast_days(_low_forecast())
    payload = build_land_check(
        ring=_ring_ph(),
        forecast=_low_forecast(),
        hotspot_payload={"results": [], "combined": {"coverage": "unknown"}},
        observation_date="2026-11-14",
    )
    assert payload["forecast"]["headline"] == annotated["headline"]
    assert payload["forecast"]["attention_day"] == annotated["attention_day"]
    assert payload["forecast"]["point"]["latitude"] == annotated["point"]["latitude"]
    assert payload["forecast"]["days"][0]["valid_date"] == "2026-11-14"
    assert payload["forecast"]["days"][0]["danger_level"] == "Low"
