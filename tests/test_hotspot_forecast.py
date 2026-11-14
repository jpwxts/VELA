"""Mindanao MODIS/VIIRS hotspot-forecast dataset and serving guards."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from vela.hotspot_coverage import COVERAGE_PATH, HOTSPOT_DAILY_COVERAGE_RULE
from vela.hotspot_forecast import COVERAGE_RULE, FEATURE_NAMES, STUDY, freeze_rules
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
    assert "no-detection pass" in HOTSPOT_DAILY_COVERAGE_RULE["pass_statement"].lower() or "no-detection" in HOTSPOT_DAILY_COVERAGE_RULE["pass_statement"]


def test_coverage_rule_rejects_empty_firms_as_negative():
    rules = freeze_rules()
    assert "BFP" in str(rules["excludes"])
    assert "fire-mask" in COVERAGE_RULE["negative"].lower() or "fire-mask" in COVERAGE_RULE["products"].lower()
    assert STUDY["id"].startswith("mindanao_")


def test_fire_mask_coverage_parquet_is_readable():
    info = fire_mask_coverage_keys(study_cells())
    assert COVERAGE_PATH.is_file()
    assert info["count"] >= 16
    assert info["negative_count"] >= 16
    frame = pd.read_parquet(COVERAGE_PATH)
    assert "label_support" in frame.columns
    assert (frame["label_support"] == "negative_supported").sum() >= 16


def test_dataset_has_coverage_backed_negatives():
    path = ROOT / "data" / "processed" / "philippines_hotspot_cell_days.parquet"
    assert path.is_file()
    frame = pd.read_parquet(path)
    assert set(FEATURE_NAMES).issubset(frame.columns)
    assert int((frame["label"] == 1).sum()) > 0
    assert int((frame["label"] == 0).sum()) >= 16
    assert frame["split"].isin(["train", "validation", "test"]).all()


def test_splits_reserve_odd_cells_and_late_dates():
    assert assign_split("2023-08-01", "2390:174") == "train"
    assert assign_split("2024-03-01", "2390:174") == "validation"
    assert assign_split("2025-02-20", "2390:174") == "test"
    assert assign_split("2023-08-01", "2391:174") == "test"


def test_pilot_trace_has_traceable_negative():
    path = ROOT / "data" / "metrics" / "philippines_hotspot_coverage_pilot_trace.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    example = payload.get("traceable_coverage_backed_negative") or payload.get("traceable_example")
    assert example is not None
    assert example.get("cell_id")
    assert example.get("ph_date")
    assert example.get("source_granules")


def test_study_cells_are_land_clipped():
    cells = study_cells()
    assert 100 < len(cells) < 2000
    assert ":" in cells[0]
    assert len(neighbor_ids(cells[0])) == 8
