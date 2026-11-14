"""Mindanao MODIS/VIIRS hotspot-forecast dataset and serving guards."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from vela.hotspot_coverage import COVERAGE_PATH, HOTSPOT_DAILY_COVERAGE_RULE
from vela.hotspot_forecast import FEATURE_NAMES, STUDY, freeze_rules
from vela.hotspot_forecast_dataset import (
    assign_split,
    fire_mask_coverage_keys,
    neighbor_ids,
    study_cells,
)


ROOT = Path(__file__).resolve().parents[1]


def test_daily_coverage_rule_defines_forecast_meaning():
    assert HOTSPOT_DAILY_COVERAGE_RULE["min_visible_land_fraction"] == 0.5
    assert "Chance of satellite-detected heat" in HOTSPOT_DAILY_COVERAGE_RULE["forecast_percentage_meaning"]


def test_count_reconciliation_explains_plus_432():
    path = ROOT / "data" / "metrics" / "philippines_hotspot_count_reconciliation.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["delta"] == 432
    assert payload["added_day_detail"]["ph_date"] == "2026-10-01"
    assert payload["added_day_detail"]["cells"] == 432
    assert payload["v2_1_square_days"] == 64368
    assert payload["v1_square_days"] == 63936


def test_fire_mask_coverage_and_dataset_negatives():
    info = fire_mask_coverage_keys(study_cells())
    assert COVERAGE_PATH.is_file()
    assert info["negative_count"] >= 16
    frame = pd.read_parquet(ROOT / "data" / "processed" / "philippines_hotspot_cell_days.parquet")
    assert set(FEATURE_NAMES).issubset(frame.columns)
    assert int((frame["label"] == 0).sum()) >= 16
    assert int((frame["label"] == 1).sum()) > 0


def test_v22_reserve_is_test_only_and_sealed():
    path = ROOT / "data" / "manifests" / "philippines_hotspot_holdout_v2_2_reserve.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["scope"] == "test_split_only"
    assert payload["status"] == "sealed_unused_for_tuning"
    assert payload["n_reserved_test_rows"] > 0
    assert "claimable_holdout_metrics" in payload


def test_model_comparison_has_six_classifier_board():
    path = ROOT / "data" / "metrics" / "philippines_hotspot_model_comparison.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["coverage_rule_version"] == "hotspot_coverage_v2_1"
    names = [row["name"] for row in payload["classifiers"]]
    assert len(names) == 6
    for row in payload["classifiers"]:
        metrics = row["metrics"]
        for key in ("accuracy", "precision", "recall", "f1", "brier_score", "n", "positives"):
            assert key in metrics
    holdout = payload["holdout"]
    assert "claimable_ex_v22_reserve" in holdout
    assert "confusion_matrix" in holdout["claimable_ex_v22_reserve"]
    assert payload["analytics"]["title"].startswith("Model performance")


def test_splits_reserve_odd_cells_and_late_dates():
    assert assign_split("2023-08-01", "2390:174") == "train"
    assert assign_split("2024-03-01", "2390:174") == "validation"
    assert assign_split("2025-02-20", "2390:174") == "test"
    assert assign_split("2023-08-01", "2391:174") == "test"


def test_study_cells_are_land_clipped():
    cells = study_cells()
    assert 100 < len(cells) < 2000
    assert len(neighbor_ids(cells[0])) == 8
    assert STUDY["id"].startswith("mindanao_")
    freeze_rules()


def test_month_future_days_are_upcoming_not_percent():
    from vela.hotspot_forecast_serve import month_forecasts_for_cell

    month = month_forecasts_for_cell("2399:175", "2026-11", ph_today="2026-11-14")
    future = [row for row in month["days"] if row["date"] > "2026-11-14"]
    assert len(future) == 16
    assert all(row["calendar_state"] == "upcoming" for row in future)
    assert all(row.get("probability_percent") is None for row in future)


def test_future_square_forecast_refuses_archive_write():
    from vela.hotspot_forecast_serve import HotspotForecastStore, forecast_for_cell

    payload = forecast_for_cell(
        cell_id="2399:175",
        issue_date_ph="2026-11-20",
        ph_today="2026-11-14",
    )
    assert payload["status"] == "upcoming"
    assert payload.get("probability_percent") is None
    assert HotspotForecastStore().get("2399:175", "2026-11-20") is None


def test_outside_study_is_unsupported():
    from vela.hotspot_forecast_serve import forecast_for_cell

    payload = forecast_for_cell(
        cell_id="2100:200",
        issue_date_ph="2026-11-14",
        ph_today="2026-11-14",
    )
    assert payload["status"] == "unsupported"
    assert payload.get("probability_percent") is None
    assert "Outside Maguindanao" in (payload.get("reason") or "")


def test_high_probability_audit_and_diagnosis_exist():
    audit = ROOT / "data" / "metrics" / "philippines_hotspot_high_probability_audit.json"
    diagnosis = ROOT / "data" / "metrics" / "philippines_hotspot_tamatalon_99pct_diagnosis.json"
    assert audit.is_file()
    assert diagnosis.is_file()
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["high_band"]["n"] >= 1
    assert payload["serving_policy"]["do_not_cap_or_rescale"] is True
    diag = json.loads(diagnosis.read_text(encoding="utf-8"))
    assert diag["selected_cell"] == "2399:175"
    assert "2026-11-14" in diag["days"]


def test_history_month_rate_never_uses_forecast_percent_helper():
    """Guardrail: forecast percents must not be labeled as month activity."""

    # Documentation-level guard: the History UI must use activity_rate for Month's activity.
    history_js = (ROOT / "app" / "static" / "js" / "history.js").read_text(encoding="utf-8")
    assert "Never put a single-day forecast percent under “Month's activity”." in history_js
    assert "lastHotspotForecast?.probability_percent" not in history_js


def test_multi_region_registry_frozen_before_outcomes():
    path = ROOT / "data" / "manifests" / "mindanao_hotspot_regions_v1.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["registered_before_looking_at_outcomes"] is True
    ids = [row["id"] for row in payload["regions"]]
    assert "maguindanao_compact_v1" in ids
    assert "bukidnon_compact_v1" in ids
    assert "davao_norte_compact_v1" in ids
    supported = ROOT / "data" / "metrics" / "mindanao_hotspot_supported_areas.json"
    assert supported.is_file()
    areas = json.loads(supported.read_text(encoding="utf-8"))
    mag = next(row for row in areas["regions"] if row["id"] == "maguindanao_compact_v1")
    assert mag["evaluated"] is True
