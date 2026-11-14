"""Mindanao MODIS/VIIRS hotspot-forecast dataset and serving guards."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from vela.hotspot_forecast import COVERAGE_RULE, FEATURE_NAMES, STUDY, freeze_rules
from vela.hotspot_forecast_dataset import assign_split, neighbor_ids, study_cells


ROOT = Path(__file__).resolve().parents[1]


def test_coverage_rule_frozen_and_excludes_weather_bfp():
    rules = freeze_rules()
    assert "BFP" in str(rules["excludes"])
    assert "weather" in str(rules["excludes"]).lower()
    assert COVERAGE_RULE["version"] == "hotspot_coverage_v1"
    assert STUDY["id"].startswith("mindanao_")


def test_dataset_exists_with_real_counts():
    path = ROOT / "data" / "processed" / "philippines_hotspot_cell_days.parquet"
    assert path.is_file()
    frame = pd.read_parquet(path)
    assert set(FEATURE_NAMES).issubset(frame.columns)
    assert frame["label"].isin([0, 1]).all()
    assert frame["split"].isin(["train", "validation", "test"]).all()
    assert int((frame["label"] == 1).sum()) > 0
    assert int((frame["label"] == 0).sum()) > 0
    # No target leakage fields required beyond issue-time features.
    assert "hours_since_last_detection" in frame.columns


def test_splits_are_chronological():
    assert assign_split("2023-08-01") == "train"
    assert assign_split("2024-03-01") == "validation"
    assert assign_split("2025-02-20") == "test"


def test_study_cells_are_land_clipped():
    cells = study_cells()
    assert 100 < len(cells) < 2000
    assert ":" in cells[0]
    assert len(neighbor_ids(cells[0])) == 8
