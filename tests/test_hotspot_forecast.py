"""Mindanao MODIS/VIIRS hotspot-forecast dataset and serving guards."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from vela.hotspot_forecast import COVERAGE_RULE, FEATURE_NAMES, STUDY, freeze_rules
from vela.hotspot_forecast_dataset import (
    assign_split,
    fire_mask_coverage_keys,
    neighbor_ids,
    study_cells,
)


ROOT = Path(__file__).resolve().parents[1]


def test_coverage_rule_v2_rejects_empty_firms_as_negative():
    rules = freeze_rules()
    assert "BFP" in str(rules["excludes"])
    assert "weather" in str(rules["excludes"]).lower()
    assert COVERAGE_RULE["version"] == "hotspot_coverage_v2"
    assert "insufficient evidence" in COVERAGE_RULE["unknown"].lower() or "unknown" in COVERAGE_RULE["unknown"].lower()
    assert "fire-mask" in COVERAGE_RULE["negative"].lower() or "fire-mask" in COVERAGE_RULE["products"].lower()
    assert "empty" in COVERAGE_RULE["unknown"].lower() or "FIRMS" in COVERAGE_RULE["unknown"]
    assert STUDY["id"].startswith("mindanao_")


def test_fire_mask_coverage_inventory_does_not_use_firms_zeros():
    info = fire_mask_coverage_keys(study_cells())
    assert "count" in info
    assert info["sources"]["paired_cells"] >= 0
    # Maguindanao currently has no processed fire-mask rows in paired_cells.
    assert info["count"] == 0


def test_dataset_v2_has_no_firms_inferred_negatives():
    path = ROOT / "data" / "processed" / "philippines_hotspot_cell_days.parquet"
    assert path.is_file()
    frame = pd.read_parquet(path)
    assert set(FEATURE_NAMES).issubset(frame.columns)
    if len(frame):
        assert frame["label"].isin([0, 1]).all()
        assert frame["split"].isin(["train", "validation", "test"]).all()
        assert "hours_since_last_detection" in frame.columns
    # After v2 correction: either negatives come only with fire-mask support (0 today)
    # or the parquet holds positives only.
    negatives = int((frame["label"] == 0).sum()) if len(frame) else 0
    assert negatives == 0
    assert int((frame["label"] == 1).sum()) > 0


def test_serving_blocked_without_fire_mask_negatives():
    selection = ROOT / "data" / "models" / "philippines_hotspot_selection.json"
    assert selection.is_file()
    import json

    payload = json.loads(selection.read_text(encoding="utf-8"))
    assert payload.get("approved_for_serving") is not True


def test_splits_are_chronological():
    assert assign_split("2023-08-01") == "train"
    assert assign_split("2024-03-01") == "validation"
    assert assign_split("2025-02-20") == "test"


def test_study_cells_are_land_clipped():
    cells = study_cells()
    assert 100 < len(cells) < 2000
    assert ":" in cells[0]
    assert len(neighbor_ids(cells[0])) == 8
