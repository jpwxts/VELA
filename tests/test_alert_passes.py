"""Distinct-pass leads and confirmation-evidence honesty checks."""

from __future__ import annotations

from vela.alert_passes import confirmation_evidence, distinct_passes, pass_summary
from vela.findings import build_findings


DALIPE_MEMBERS = [
    {
        "platform": "NOAA-21",
        "acq_date": "2026-11-07",
        "acq_time": "04:33",
        "acq_date_ph": "2026-11-07",
        "acq_time_ph": "12:33",
        "lat": 12.01808,
        "lon": 123.71458,
    },
    {
        "platform": "NOAA-20",
        "acq_date": "2026-11-07",
        "acq_time": "05:31",
        "acq_date_ph": "2026-11-07",
        "acq_time_ph": "13:31",
        "lat": 12.01192,
        "lon": 123.71716,
    },
    # Neighboring pixel from the same NOAA-21 pass must not create a third pass.
    {
        "platform": "NOAA-21",
        "acq_date": "2026-11-07",
        "acq_time": "04:33",
        "lat": 12.0185,
        "lon": 123.7150,
    },
]


def test_dalipe_style_repeat_pass_lead():
    summary = pass_summary(DALIPE_MEMBERS, observation_date="2026-11-07")
    assert summary["pass_count"] == 2
    assert summary["span_minutes"] == 58
    assert summary["lead"] == "Heat detected twice, 58 minutes apart."
    names = [row["name"] for row in summary["satellites"]]
    assert names == ["NOAA-21", "NOAA-20"]
    assert summary["satellites"][0]["acq_time_ph"] == "12:33"
    assert summary["satellites"][1]["acq_time_ph"] == "13:31"


def test_neighbor_pixels_same_pass_count_once():
    passes = distinct_passes(DALIPE_MEMBERS)
    assert len(passes) == 2
    n21 = next(row for row in passes if row["platform"] == "NOAA-21")
    assert n21["detection_count"] == 2


def test_single_pass_lead():
    summary = pass_summary(
        [{"platform": "NOAA-20", "acq_date": "2026-11-07", "acq_time": "05:31"}],
        observation_date="2026-11-07",
    )
    assert summary["pass_count"] == 1
    assert summary["lead"] == "Heat detected once."


def test_unknown_coverage_empty_case():
    summary = pass_summary(
        [],
        observation_date="2026-11-07",
        empty=True,
        coverage_unknown=True,
    )
    assert summary["lead"] == "No heat was reported here. Satellite visibility is unknown."
    assert summary["coverage_unknown"] is True


def test_confirmation_evidence_reports_missing_labels():
    block = confirmation_evidence()
    assert block["status"] == "labels_unavailable"
    assert block["percentage"] is None
    assert "Independently verified Philippine" in block["missing_dataset"]
    assert "never converted" in block["forbidden_conversions"]


def test_build_findings_puts_model_in_research_and_confirmation_on_panel():
    payload = build_findings(
        scope="square",
        observation_date="2026-11-07",
        place_name="Barangay Dalipe, Masbate",
        lat=12.015,
        lon=123.716,
        members=DALIPE_MEMBERS,
        platforms=[{"name": "NOAA-21"}, {"name": "NOAA-20"}],
        weather_fixture={
            "valid_time": "2026-11-07T12:00:00Z",
            "temperature_c": 30.0,
            "relative_humidity_percent": 70.0,
            "kind": "historical",
        },
        region="Philippines",
    )
    assert payload["satellite"]["lead"] == "Heat detected twice, 58 minutes apart."
    assert payload["satellite"]["pass_count"] == 2
    assert payload["confirmation"]["status"] == "labels_unavailable"
    assert payload["model"]["panel"] == "research"
    assert "model" in payload["research"]
    assert payload["research"]["confirmation"]["percentage"] is None
