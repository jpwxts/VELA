"""Philippine 24-hour onset forecast scaffolding: audit, features, store, comparison."""

from __future__ import annotations

import numpy as np

from vela.onset_features import build_issue_time_features
from vela.onset_forecast import (
    TARGET_DEFINITION,
    forecast_for_cell,
    labels_sufficient,
    load_audit,
    load_split,
    polygon_onset_summary,
    valid_interval,
)
from vela.onset_models import compare_on_validation
from vela.onset_store import OnsetForecastStore


def test_target_definition_is_onset_not_harmonization():
    assert "new wildfire" in TARGET_DEFINITION["question"].lower()
    assert any("harmonization" in item.lower() for item in TARGET_DEFINITION["not_this_target"])


def test_audit_blocks_publishing_without_labels():
    audit = load_audit()
    assert audit.get("usable_unique_wildfire_starts") == 0
    assert audit.get("square_days_with_credible_reporting_coverage") == 0
    assert labels_sufficient(audit) is False
    split = load_split()
    assert split.get("registered_before_fitting") is True
    assert split.get("row_counts", {}).get("train") == 0


def test_forecast_for_cell_is_unavailable_not_zero():
    payload = forecast_for_cell(cell_id="2393:174", issue_date="2026-11-14", scope="mindanao")
    assert payload["status"] == "unavailable"
    assert payload["probability"] is None
    assert payload["probability_percent"] is None
    assert "0%" not in (payload.get("reason") or "")
    assert payload["valid_interval"]["start_manila"].startswith("2026-11-14T00:00:00")


def test_issue_time_features_ignore_post_midnight_passes():
    # Philippine midnight 2026-11-14 == 2026-11-13T16:00:00Z.
    detections = [
        {
            "lat": 6.85779,
            "lon": 124.05852,
            "acq_date": "2026-11-13",
            "acq_time": "10:00",
            "retrieved_at": "2026-11-13T10:05:00+00:00",
            "platform": "NOAA-21",
        },
        {
            "lat": 6.85779,
            "lon": 124.05852,
            "acq_date": "2026-11-13",
            "acq_time": "18:00",
            "retrieved_at": "2026-11-13T18:05:00+00:00",
            "platform": "NOAA-20",
        },
    ]
    features = build_issue_time_features(
        cell_id="2393:174",
        issue_date_ph="2026-11-14",
        detections=detections,
        weather_forecast=None,
    )
    assert features["values"]["heat_detections_in_cell_prior_24h"] == 1.0
    assert "forecast_temp_c_next_24h" in features["missing_features"]
    assert features["reduced_feature_baseline"] is True


def test_onset_store_preserves_first_issue(tmp_path):
    store = OnsetForecastStore(tmp_path / "onset.sqlite")
    first = store.put_if_absent(
        {
            "scope": "mindanao",
            "cell_id": "2393:174",
            "issue_date_ph": "2026-11-14",
            "probability": 0.12,
            "model_version": "test-v1",
            "feature_schema_version": "onset_features_v1",
            "historical_simulation": False,
        }
    )
    second = store.put_if_absent(
        {
            "scope": "mindanao",
            "cell_id": "2393:174",
            "issue_date_ph": "2026-11-14",
            "probability": 0.99,
            "model_version": "test-v2",
            "feature_schema_version": "onset_features_v1",
            "historical_simulation": False,
        }
    )
    assert first["probability"] == 0.12
    assert second["probability"] == 0.12
    store.record_outcome(
        cell_id="2393:174",
        issue_date_ph="2026-11-14",
        status="unknown",
        label="Outcome unknown",
    )
    assert store.outcome_for(cell_id="2393:174", issue_date_ph="2026-11-14")["status"] == "unknown"


def test_polygon_summary_never_averages():
    cells = [
        {"status": "unavailable", "cell_id": "1:1", "probability": None},
        {"status": "issued", "cell_id": "1:2", "probability": 0.2, "probability_percent": 20},
        {"status": "issued", "cell_id": "1:3", "probability": 0.4, "probability_percent": 40},
    ]
    summary = polygon_onset_summary(cells)
    assert summary["polygon_probability"] is None
    assert summary["highest_estimated_square"]["cell_id"] == "1:3"


def test_six_model_comparison_protocol_on_synthetic():
    rng = np.random.default_rng(0)
    x_train = rng.normal(size=(40, 4))
    y_train = (x_train[:, 0] + rng.normal(scale=0.3, size=40) > 0.2).astype(int)
    x_valid = rng.normal(size=(20, 4))
    y_valid = (x_valid[:, 0] + rng.normal(scale=0.3, size=20) > 0.2).astype(int)
    seasons_train = ["dry"] * 40
    seasons_valid = ["dry"] * 20
    result = compare_on_validation(
        x_train,
        y_train,
        x_valid,
        y_valid,
        season_keys_train=seasons_train,
        season_keys_valid=seasons_valid,
    )
    assert result["baseline"]["name"] == "regional_seasonal_event_rate"
    assert len(result["classifiers"]) == 6
    assert result["winner"]["name"] in {row["name"] for row in result["classifiers"]}
    assert "Brier" in result["winner"]["why"]


def test_valid_interval_is_manila_day():
    interval = valid_interval("2026-11-14")
    assert interval["start_manila"].startswith("2026-11-14T00:00:00")
    assert interval["end_manila"].startswith("2026-11-15T00:00:00")
