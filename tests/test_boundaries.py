"""Island-group presets clip FIRMS points before area grouping."""

from __future__ import annotations

from vela.boundaries import load_preset, point_in_geometry
from vela.land_check import annotate_forecast_days, classify_detections


def test_mindanao_excludes_masbate_and_luzon():
    geom = load_preset("mindanao")["geometry"]
    assert point_in_geometry(125.09, 7.01, geom) is True  # Kidapawan-ish
    assert point_in_geometry(123.6, 12.35, geom) is False  # Masbate
    assert point_in_geometry(121.506, 18.3286, geom) is False  # Luzon


def test_classify_detections_uses_multipolygon_not_bbox():
    geom = load_preset("mindanao")["geometry"]
    payload = {
        "combined": {"coverage": "observed"},
        "results": [
            {
                "platform": "NOAA-20",
                "status": "ok",
                "coverage": "observed",
                "product": "VIIRS_NOAA20_NRT",
                "hotspots": [
                    {
                        "lat": 7.01,
                        "lon": 125.09,
                        "platform": "NOAA-20",
                        "acq_date": "2026-11-07",
                        "acq_time": "05:00",
                    },
                    {
                        "lat": 12.35,
                        "lon": 123.6,
                        "platform": "NOAA-20",
                        "acq_date": "2026-11-07",
                        "acq_time": "05:01",
                    },
                    {
                        "lat": 18.3286,
                        "lon": 121.506,
                        "platform": "NOAA-20",
                        "acq_date": "2026-11-07",
                        "acq_time": "05:33",
                    },
                ],
            }
        ],
    }
    heat = classify_detections(payload, geometry=geom)
    assert heat["inside_count"] == 1
    assert heat["hotspot_areas"]["area_count"] == 1
    assert heat["hotspot_areas"]["detection_count"] == 1
    assert max(row["lat"] for row in heat["inside"]) < 10


def test_all_low_forecast_avoids_arbitrary_peak_day():
    forecast = {
        "ok": True,
        "days": [
            {
                "valid_date": "2026-11-15",
                "fire_danger": {"status": "measured", "fwi": 5.0, "ranking": None},
                "temperature_max_c": {"status": "ok", "value": 30},
                "relative_humidity_min_percent": {"status": "ok", "value": 60},
                "forecast_rain_mm": {"status": "quiet", "value": 0},
                "wind_speed_max_m_s": {"status": "ok", "value": 3},
            },
            {
                "valid_date": "2026-11-16",
                "fire_danger": {"status": "measured", "fwi": 4.0, "ranking": None},
                "temperature_max_c": {"status": "ok", "value": 29},
                "relative_humidity_min_percent": {"status": "ok", "value": 62},
                "forecast_rain_mm": {"status": "quiet", "value": 0},
                "wind_speed_max_m_s": {"status": "ok", "value": 2},
            },
        ],
    }
    annotated = annotate_forecast_days(forecast)
    assert annotated["headline"] == "Low throughout the available forecast"
    assert annotated["attention_day"] is None
