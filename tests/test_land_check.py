"""Land-check keeps forecast classes, heat evidence, and incidents separate."""

from __future__ import annotations

from vela.land_check import (
    annotate_forecast_days,
    build_land_check,
    class_from_fwi,
    classify_detections,
    danger_class_for_day,
    normalize_ring,
    point_in_ring,
)


def test_gwis_fwi_classes_match_documented_thresholds():
    assert class_from_fwi(11.19) == "Low"
    assert class_from_fwi(11.2) == "Moderate"
    assert class_from_fwi(36.0) == "High"
    assert class_from_fwi(50.0) == "Extreme"
    assert class_from_fwi(70.0) == "Very Extreme"
    assert danger_class_for_day({"status": "unavailable"})["level"] is None


def test_point_inside_and_nearby_use_coordinates_not_squares():
    ring = normalize_ring([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    assert point_in_ring(0.5, 0.5, ring)
    assert not point_in_ring(1.5, 0.5, ring)
    payload = {
        "date": "2026-11-10",
        "results": [
            {
                "platform": "NOAA-20",
                "status": "ok",
                "coverage": "unknown",
                "hotspots": [
                    {
                        "lat": 0.5,
                        "lon": 0.5,
                        "acq_date": "2026-11-10",
                        "acq_time": "10:00",
                        "acq_time_raw": "1000",
                        "platform": "NOAA-20",
                    },
                    {
                        "lat": 0.5,
                        "lon": 1.02,
                        "acq_date": "2026-11-10",
                        "acq_time": "11:00",
                        "acq_time_raw": "1100",
                        "platform": "NOAA-21",
                    },
                ],
            },
            {
                "platform": "Suomi-NPP",
                "status": "product_unavailable",
                "coverage": "unknown",
                "hotspots": [],
            },
        ],
    }
    heat = classify_detections(payload, ring, nearby_km=5.0)
    assert heat["inside_count"] == 1
    assert heat["nearby_count"] == 1
    assert heat["inside"][0]["platform"] == "NOAA-20"
    assert heat["inside"][0]["acq_time_raw"] == "1000"
    assert heat["nearby"][0]["platform"] == "NOAA-21"
    assert "Satellite coverage is unverified" not in heat["lead"]
    # Map areas keep only polygon-retained detections, not nearby-outside points.
    assert heat["hotspot_areas"]["detection_count"] == 1
    assert heat["hotspot_areas"]["area_count"] == 1
    feeds = {row["platform"]: row for row in heat["feeds"]}
    assert feeds["NOAA-20"]["count"] == 1
    assert feeds["Suomi-NPP"]["status"] == "unavailable"
    assert "unavailable for this date" in feeds["Suomi-NPP"]["text"]


def test_unknown_empty_heat_copy():
    ring = normalize_ring([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    heat = classify_detections(
        {"results": [{"platform": "Aqua", "status": "no_hotspots", "coverage": "unknown", "hotspots": []}]},
        ring,
    )
    assert heat["status"] == "none_unknown"
    assert heat["lead"] == (
        "No satellite heat readings returned for this search inside your boundary. Clear-view coverage is unknown."
    )


def test_peak_headline_and_no_combined_score():
    forecast = {
        "ok": True,
        "issued_at": "2026-11-11T12:00:00+00:00",
        "point": {"latitude": 1.0, "longitude": 2.0},
        "days": [
            {
                "valid_date": "2026-11-12",
                "lead_days": 0,
                "temperature_max_c": {"status": "measured", "value": 30.0},
                "relative_humidity_min_percent": {"status": "measured", "value": 18.0},
                "wind_speed_max_m_s": {"status": "measured", "value": 8.0},
                "wind_gust_max_m_s": {"status": "quiet", "value": 0.0},
                "forecast_rain_mm": {"status": "quiet", "value": 0.0},
                "fire_danger": {"status": "measured", "fwi": 36.0, "ranking": 75.0},
            },
            {
                "valid_date": "2026-11-13",
                "lead_days": 1,
                "temperature_max_c": {"status": "measured", "value": 22.0},
                "relative_humidity_min_percent": {"status": "measured", "value": 40.0},
                "wind_speed_max_m_s": {"status": "measured", "value": 3.0},
                "wind_gust_max_m_s": {"status": "quiet", "value": 0.0},
                "forecast_rain_mm": {"status": "measured", "value": 2.0},
                "fire_danger": {"status": "measured", "fwi": 5.0, "ranking": 10.0},
            },
        ],
    }
    annotated = annotate_forecast_days(forecast)
    assert "highest forecast fire danger" in annotated["headline"]
    assert annotated["headline"].endswith("High.")
    assert annotated["attention_day"] == "2026-11-12"
    assert "humidity" in annotated["headline_explanation"].lower()
    assert annotated["forecast_status"]["kind"] == "archive"
    ring = normalize_ring([[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1]])
    payload = build_land_check(
        ring=ring,
        forecast=forecast,
        hotspot_payload={"results": [], "combined": {"coverage": "unknown"}},
        observation_date="2026-11-10",
    )
    assert "not combined into a score" in payload["separation_note"]
    assert "highest forecast fire danger" in payload["questions"]["forecast_danger"]
    assert "no feed completed successfully" in payload["questions"]["satellite_heat"]


def test_zero_rain_and_missing_values_are_distinct():
    forecast = {
        "ok": True,
        "issued_at": "2026-11-11T19:51:00+00:00",
        "point": {"latitude": -3.27, "longitude": -66.45},
        "days": [
            {
                "valid_date": "2026-11-11",
                "lead_days": 0,
                "temperature_max_c": {"status": "measured", "value": 33.0},
                "relative_humidity_min_percent": {"status": "measured", "value": 40.0},
                "wind_speed_max_m_s": {"status": "measured", "value": 2.0},
                "wind_gust_max_m_s": {"status": "quiet", "value": 0.0},
                "forecast_rain_mm": {"status": "quiet", "value": 0.0},
                "fire_danger": {"status": "measured", "fwi": 0.0, "ranking": 10.0},
            }
        ],
    }
    annotated = annotate_forecast_days(forecast)
    assert "0 mm" in annotated["days"][0]["explanation"]
    assert "Fire Weather Index 0.0" in annotated["days"][0]["explanation"]
    empty = annotate_forecast_days(
        {
            "ok": True,
            "days": [
                {
                    "valid_date": "2026-11-11",
                    "temperature_max_c": {"status": "missing", "value": None},
                    "relative_humidity_min_percent": {"status": "missing", "value": None},
                    "wind_speed_max_m_s": {"status": "missing", "value": None},
                    "wind_gust_max_m_s": {"status": "missing", "value": None},
                    "forecast_rain_mm": {"status": "missing", "value": None},
                    "fire_danger": {"status": "unavailable", "fwi": None},
                }
            ],
        }
    )
    assert empty["headline"] == "Forecast values unavailable"
