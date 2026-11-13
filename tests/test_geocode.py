"""Place identification from Nominatim reverse payloads (mocked; no network)."""

from __future__ import annotations

import json

from app.db import ResponseCache
from app.geocode import (
    SOURCE,
    format_place_result,
    identify_members,
    identify_point,
    identify_selection,
    reverse_lookup,
)


def _cerrado_payload():
    return {
        "lat": "-14.1917",
        "lon": "-50.1885",
        "name": "Nova Xavantina",
        "display_name": "Nova Xavantina, Mato Grosso, Brazil",
        "class": "place",
        "type": "town",
        "boundingbox": ["-14.80", "-14.40", "-52.60", "-52.20"],
        "address": {
            "town": "Nova Xavantina",
            "municipality": "Nova Xavantina",
            "state": "Mato Grosso",
            "region": "Central-West Region",
            "country": "Brazil",
            "country_code": "br",
        },
    }


def _arnhem_payload():
    return {
        "lat": "-12.4500",
        "lon": "134.9000",
        "name": "Arnhem Land",
        "display_name": "Arnhem Land, Northern Territory, Australia",
        "class": "place",
        "type": "region",
        "boundingbox": ["-14.5", "-11.0", "133.0", "137.0"],
        "address": {
            "state_district": "Arnhem Land",
            "state": "Northern Territory",
            "country": "Australia",
            "country_code": "au",
        },
    }


def _philippines_payload():
    return {
        "lat": "10.7202",
        "lon": "122.5621",
        "name": "Jaro",
        "display_name": "Jaro, Iloilo City, Iloilo, Western Visayas, Philippines",
        "class": "place",
        "type": "suburb",
        "boundingbox": ["10.70", "10.74", "122.54", "122.58"],
        "address": {
            "suburb": "Jaro",
            "city": "Iloilo City",
            "province": "Iloilo",
            "region": "Western Visayas",
            "country": "Philippines",
            "country_code": "ph",
        },
    }


def _forest_payload():
    return {
        "lat": "-15.2000",
        "lon": "-56.1000",
        "name": "Chapada dos Guimarães National Park",
        "class": "boundary",
        "type": "national_park",
        "boundingbox": ["-15.6", "-14.9", "-56.4", "-55.7"],
        "address": {
            "national_park": "Chapada dos Guimarães National Park",
            "state": "Mato Grosso",
            "country": "Brazil",
            "country_code": "br",
        },
    }


def test_format_settlement_inside_uses_hierarchy_without_duplicates():
    result = format_place_result(_cerrado_payload(), lat=-14.19, lon=-50.19, mode="point")
    assert result["relation"] == "inside"
    assert result["primary"] == "Nova Xavantina"
    assert "Nova Xavantina" in result["label"]
    assert result["label"].count("Nova Xavantina") == 1
    assert "Mato Grosso" in result["label"]
    assert "Brazil" in result["label"]
    assert result["source"]["name"] == SOURCE["name"]


def test_format_center_mode_prefixes_area_near():
    result = format_place_result(_cerrado_payload(), lat=-14.19, lon=-50.19, mode="center")
    assert result["relation"] == "area_near"
    assert result["label"].startswith("Area near ")


def test_format_named_park_inside():
    result = format_place_result(_forest_payload(), lat=-15.2, lon=-56.1, mode="point")
    assert result["relation"] == "inside"
    assert "Chapada dos Guimarães National Park" in result["label"]


def test_format_near_settlement_when_far_from_named_point():
    payload = {
        "lat": "-12.0000",
        "lon": "134.0000",
        "name": "Maningrida",
        "class": "place",
        "type": "town",
        "boundingbox": ["-12.10", "-11.90", "134.10", "134.30"],
        "address": {
            "state": "Northern Territory",
            "country": "Australia",
            "country_code": "au",
        },
    }
    result = format_place_result(payload, lat=-12.45, lon=134.90, mode="point")
    assert result["relation"] == "near"
    assert result["label"].startswith("Near Maningrida")
    assert "approximately" in result["label"]


def test_format_unavailable_falls_back_to_coordinates():
    result = format_place_result(None, lat=-10.12345, lon=140.54321, mode="point")
    assert result["relation"] == "coordinates"
    assert result["status"] == "unavailable"
    assert result["label"] == "-10.12345, 140.54321"


def test_identify_members_reports_multiple_places():
    def getter(url, params, headers):
        lat = float(params["lat"])
        if lat < -14.2:
            return {
                "lat": params["lat"],
                "lon": params["lon"],
                "name": "Place A",
                "boundingbox": ["-14.25", "-14.15", "-50.25", "-50.15"],
                "address": {"village": "Place A", "state": "Mato Grosso", "country": "Brazil"},
            }
        return {
            "lat": params["lat"],
            "lon": params["lon"],
            "name": "Place B",
            "boundingbox": ["-14.15", "-14.05", "-50.15", "-50.05"],
            "address": {"village": "Place B", "state": "Mato Grosso", "country": "Brazil"},
        }

    result = identify_members(
        [
            {"lat": -14.22, "lon": -50.20},
            {"lat": -14.10, "lon": -50.10},
        ],
        center_lat=-14.16,
        center_lon=-50.15,
        getter=getter,
    )
    assert result["multiple"] is True
    assert "Place A" in result["label"] and "Place B" in result["label"]
    assert result["label"].startswith("Readings span")


def test_identify_members_falls_back_to_center(tmp_path):
    calls = {"n": 0}

    def getter(url, params, headers):
        calls["n"] += 1
        return _arnhem_payload()

    # No usable member coords → center path.
    result = identify_selection(
        mode="members",
        members=[{"lat": "bad", "lon": "bad"}],
        center_lat=-12.45,
        center_lon=134.9,
        getter=getter,
    )
    assert result["relation"] == "area_near"
    assert "Arnhem Land" in result["label"] or "Northern Territory" in result["label"]
    assert calls["n"] == 1


def test_reverse_lookup_uses_cache(tmp_path):
    cache = ResponseCache(tmp_path / "places.sqlite")
    calls = {"n": 0}

    def getter(url, params, headers):
        calls["n"] += 1
        return _philippines_payload()

    first = reverse_lookup(10.7202, 122.5621, cache=cache, getter=getter)
    second = reverse_lookup(10.7203, 122.5622, cache=cache, getter=getter)
    assert first["name"] == "Jaro"
    assert second["name"] == "Jaro"
    assert calls["n"] == 1


def test_identify_point_philippines_label():
    result = identify_point(
        10.7202,
        122.5621,
        getter=lambda url, params, headers: _philippines_payload(),
    )
    assert result["barangay"] == "Jaro"
    assert result["municipality"] == "Iloilo City"
    assert result["province"] == "Iloilo"
    assert result["region"] == "Western Visayas"
    assert result["primary"] == "Jaro"
    assert result["label"] == "Barangay Jaro, Iloilo City, Iloilo"
    assert result["timezone"] == "Asia/Manila"
    assert result["relation"] == "inside"
