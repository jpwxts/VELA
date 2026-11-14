"""Public Philippine FIRMS snapshot used for team review without a map key."""

from __future__ import annotations

from pathlib import Path

from vela.public_hotspots import build_public_land_check, geojson_path, load_geojson


def test_philippines_snapshot_exists_and_counts():
    path = geojson_path("2026-11-07")
    assert path.is_file()
    collection = load_geojson("2026-11-07")
    assert collection["type"] == "FeatureCollection"
    features = collection["features"]
    assert len(features) == 47
    for feature in features:
        lon, lat = feature["geometry"]["coordinates"]
        assert feature["geometry"]["type"] == "Point"
        assert isinstance(lon, float) and isinstance(lat, float)
        props = feature["properties"]
        assert props["satellite"]
        assert props["acq_datetime_utc"].endswith("Z")
        assert props["acq_date_ph"]
        assert props["acq_time_ph"]
        assert props["place_or_coordinates"]


def test_mindanao_filter_drops_masbate_and_updates_counts():
    philippines = build_public_land_check(day="2026-11-07", region="philippines")
    mindanao = build_public_land_check(day="2026-11-07", region="mindanao")
    assert philippines["counts"]["detections"] == 47
    assert mindanao["counts"]["detections"] == 12
    ph_lats = [row["lat"] for row in philippines["heat"]["inside"]]
    mind_lats = [row["lat"] for row in mindanao["heat"]["inside"]]
    assert max(ph_lats) > 15
    assert max(mind_lats) < 11
    masbate_ph = [
        row
        for row in philippines["heat"]["inside"]
        if 11.8 <= row["lat"] <= 12.3 and 123.5 <= row["lon"] <= 124.0
    ]
    masbate_mind = [
        row
        for row in mindanao["heat"]["inside"]
        if 11.8 <= row["lat"] <= 12.3 and 123.5 <= row["lon"] <= 124.0
    ]
    assert masbate_ph
    assert not masbate_mind


def test_late_utc_pass_uses_next_philippine_calendar_day():
    collection = load_geojson("2026-11-07")
    late = [
        feature
        for feature in collection["features"]
        if str(feature["properties"]["acq_time_utc"]).startswith("17")
        or str(feature["properties"]["acq_time_utc"]).startswith("18")
    ]
    assert late
    for feature in late:
        assert feature["properties"]["acq_date_utc"] == "2026-11-07"
        assert feature["properties"]["acq_date_ph"] == "2026-11-08"
