"""Map click → findings → History heat overlay for the Philippine snapshot."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from vela.firms_day import merge_hotspot_payloads, ph_day_for_utc
from vela.grid import cell_identifier, indices
from vela.history import attach_heat_overlay, build_monthly_history
from vela.public_hotspots import build_public_land_check, load_geojson


client = TestClient(app)


def test_snapshot_splits_47_into_43_and_4_philippine_days():
    collection = load_geojson("2026-11-07")
    assert len(collection["features"]) == 47
    ph = {}
    for feature in collection["features"]:
        props = feature["properties"]
        day = props["acq_date_ph"]
        ph[day] = ph.get(day, 0) + 1
        if str(props["acq_time_utc"]).startswith(("17", "18")):
            assert props["acq_date_ph"] == "2026-11-08"
            assert ph_day_for_utc(props["acq_date_utc"], props["acq_time_utc"]) == "2026-11-08"
    assert ph == {"2026-11-07": 43, "2026-11-08": 4}


def test_maguindanao_marker_findings_and_history_heat_overlay():
    lat, lon = 6.85779, 124.05852
    x, y = indices(lon, lat)
    cell = cell_identifier(int(x), int(y))
    assert cell == "2393:174"

    public = client.get("/api/public/philippines/2026-11-07?region=philippines").json()
    area = next(item for item in public["heat"]["hotspot_areas"]["areas"] if item["cell_id"] == cell)
    member = area["members"][0]
    assert member["platform"] == "NOAA-21"
    assert member["acq_date"] == "2026-11-07"
    assert member["acq_time"] == "04:33"

    findings = client.post(
        "/api/findings",
        json={
            "scope": "square",
            "date": area["observation_day"],
            "selected_date": "2026-11-01",
            "cell_id": cell,
            "lat": lat,
            "lon": lon,
            "members": [
                {
                    "platform": member["platform"],
                    "acq_date": member["acq_date"],
                    "acq_time": member["acq_time"],
                    "acq_date_ph": member.get("acq_date_ph"),
                    "acq_time_ph": member.get("acq_time_ph"),
                    "lat": member["lat"],
                    "lon": member["lon"],
                }
            ],
            "satellites": [{"name": "NOAA-21"}],
            "region": "Philippines",
        },
    ).json()
    assert findings["satellite"]["lead"] == "Heat detected once."
    assert findings["satellite"]["pass_count"] == 1
    assert findings["date_mismatch"]["active"] is True
    assert findings["model"]["calibration_pending"] or findings["model"]["status"] in {
        "noaa_raw",
        "firms_only",
        "unavailable",
    }

    ring = public["display_ring"] or public["polygon"]["coordinates"][0]
    history = client.post(
        "/api/history/month",
        json={"coordinates": ring, "year": 2026, "month": 11},
    ).json()
    day = next(item for item in history["days"] if item["date"] == "2026-11-07")
    assert day["display_kind"] == "heat"
    assert day["heat_count"] == 47 or day["heat_count"] >= 40
    assert "Heat readings available" in (day["display_detail"] or "")
    assert day["activity_rate"] is None
    day8 = next(item for item in history["days"] if item["date"] == "2026-11-08")
    assert day8["display_kind"] == "heat"
    # Snapshot baseline is 4; the observation store may add later Live refreshes.
    assert day8["heat_count"] >= 4


def test_failed_feed_stays_failed_in_merge():
    merged = merge_hotspot_payloads(
        [
            {
                "configured": True,
                "date": "2026-11-07",
                "results": [
                    {
                        "platform": "Aqua",
                        "status": "request_failed",
                        "coverage": "unknown",
                        "count": 0,
                        "hotspots": [],
                    }
                ],
            }
        ],
        observation_date="2026-11-07",
    )
    assert merged["feeds"][0]["outcome"] == "failed"
    assert merged["total_count"] == 0


def test_zambia_fixture_returns_numeric_estimate():
    payload = client.get("/api/findings/zambia-fixture").json()
    assert payload["model"]["status"] == "estimated_suomi"
    assert payload["model"]["model_probability"] is not None
    assert abs(payload["model"]["model_probability"] - 0.010412366436853273) < 1e-9


def test_attach_heat_overlay_replaces_no_stored_observations_label():
    ring = [[120.0, 14.0], [121.0, 14.0], [121.0, 15.0], [120.0, 15.0], [120.0, 14.0]]
    payload = build_monthly_history(ring, 2026, 11)
    enriched = attach_heat_overlay(
        payload,
        heat_days=[{"date": "2026-11-07", "count": 12, "queried": True}],
        checked_days=["2026-11-07"],
    )
    day = next(item for item in enriched["days"] if item["date"] == "2026-11-07")
    assert day["display_label"] == "Satellite heat readings"
    assert "not processed" in (day["display_detail"] or "").lower()
    unchecked = next(item for item in enriched["days"] if item["date"] == "2026-11-02")
    assert unchecked["display_label"] == "Not checked"
