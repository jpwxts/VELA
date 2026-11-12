"""A one-feature pilot logistic regression. This is not the final model and not Reveal MODIS."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from vela.settings import DATA_DIR

PILOT_PATH = DATA_DIR / "models" / "pilot_logistic_log1p.joblib"
PILOT_REPORT_PATH = DATA_DIR / "models" / "pilot_report.json"
FIRE_COLUMN = "viirs_hotspot_pixel_count"
OMITTED_ACTIVITY_DATE = "2019-08-23"


def log1p_viirs_fire_pixels(values):
    """The only pilot predictor. It is the VIIRS fire-pixel count, available without MODIS."""

    array = np.asarray(values, dtype=float)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.shape[1] != 1:
        raise ValueError("The pilot model accepts one column: the VIIRS fire-pixel count.")
    return np.log1p(np.clip(array, a_min=0, a_max=None))


def make_pilot_pipeline() -> Pipeline:
    """L2-regularized logistic regression with the observed class proportions."""

    return Pipeline(
        [
            (
                "log1p_viirs_fire_pixels",
                FunctionTransformer(log1p_viirs_fire_pixels, validate=False),
            ),
            (
                "model",
                LogisticRegression(
                    C=1.0,
                    solver="lbfgs",
                    class_weight=None,
                    max_iter=1000,
                ),
            ),
        ]
    )


def verify_table(frame: pd.DataFrame) -> dict:
    if "eligible" in frame.columns and not bool(frame["eligible"].all()):
        raise RuntimeError("paired_cells.parquet contains rows that are not eligible.")
    dates = set(frame["local_date"].astype(str))
    if OMITTED_ACTIVITY_DATE in dates:
        raise RuntimeError(f"{OMITTED_ACTIVITY_DATE} is in the eligible table.")
    duplicates = int(frame.duplicated(["cell_id", "local_date"]).sum())
    positives = int(frame["modis_detected"].fillna(False).astype(bool).sum())
    summary = {
        "eligible_cells": int(len(frame)),
        "modis_positives": positives,
        "duplicate_cell_days": duplicates,
        "eligible_dates": sorted(dates),
    }
    expected = {
        "eligible_cells": 5451,
        "modis_positives": 24,
        "duplicate_cell_days": 0,
    }
    mismatches = {key: (summary[key], expected[key]) for key in expected if summary[key] != expected[key]}
    if mismatches:
        raise RuntimeError(f"Pilot table does not match the checked counts: {mismatches}")
    return summary


def training_diagnostics(frame: pd.DataFrame, probabilities: np.ndarray) -> list[dict]:
    """In-sample rates for eligible dates only. A date with no eligible cells is omitted."""

    work = frame.copy()
    work["_probability"] = np.asarray(probabilities, dtype=float)
    rows = []
    for day, part in work.groupby(work["local_date"].astype(str), sort=True):
        if len(part) == 0 or str(day) == OMITTED_ACTIVITY_DATE:
            continue
        rows.append(
            {
                "local_date": str(day),
                "cells": int(len(part)),
                "raw_viirs_positive_rate": float((part[FIRE_COLUMN].astype(float) >= 1).mean()),
                "mean_predicted_probability": float(part["_probability"].mean()),
                "observed_modis_positive_rate": float(part["modis_detected"].fillna(False).astype(bool).mean()),
                "label": "training_diagnostic",
            }
        )
    return rows


def fit_pilot(table: Path | None = None) -> dict:
    path = table or (DATA_DIR / "processed" / "paired_cells.parquet")
    frame = pd.read_parquet(path)
    checked = verify_table(frame)
    if not bool((frame["data_origin"] == "nasa").all()):
        raise RuntimeError("The pilot table is not entirely marked as NASA observations.")
    counts = frame[[FIRE_COLUMN]].to_numpy(dtype=float)
    target = frame["modis_detected"].fillna(False).astype(int).to_numpy()
    pipeline = make_pilot_pipeline()
    pipeline.fit(counts, target)
    artifact = {
        "label": "pilot",
        "purpose": "training diagnostic only",
        "not_for_reveal": True,
        "not_the_final_model": True,
        "pipeline": pipeline,
        "feature": "log1p(viirs_hotspot_pixel_count)",
        "excluded_predictors": [
            "MODIS measurements",
            "shared-coverage fields",
            "cell ids",
            "dates",
        ],
        "class_weight": None,
        "penalty": "l2",
        "C": 1.0,
        "training_rows": checked["eligible_cells"],
        "training_positives": checked["modis_positives"],
        "eligible_dates": checked["eligible_dates"],
        "omitted_from_activity_summary": [OMITTED_ACTIVITY_DATE],
    }
    PILOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, PILOT_PATH)
    loaded = joblib.load(PILOT_PATH)
    probabilities = loaded["pipeline"].predict_proba(counts)[:, 1]
    if probabilities.min() < 0 or probabilities.max() > 1:
        raise RuntimeError("Reloaded pilot probabilities fell outside 0 to 1.")
    model = loaded["pipeline"].named_steps["model"]
    if model.class_weight is not None:
        raise RuntimeError("Pilot logistic regression changed the class proportions.")
    diagnostics = training_diagnostics(frame, probabilities)
    if any(row["local_date"] == OMITTED_ACTIVITY_DATE for row in diagnostics):
        raise RuntimeError(f"{OMITTED_ACTIVITY_DATE} appeared in the activity summary.")
    report = {
        "label": "pilot",
        "purpose": "training diagnostic only",
        "not_for_reveal": True,
        "not_the_final_model": True,
        "artifact": str(PILOT_PATH),
        "feature": artifact["feature"],
        "class_weight": None,
        "penalty": "l2",
        "C": 1.0,
        "intercept": float(model.intercept_[0]),
        "coefficient_on_log1p_count": float(model.coef_[0, 0]),
        "probability_min": float(probabilities.min()),
        "probability_max": float(probabilities.max()),
        "checks": checked,
        "omitted_from_activity_summary": [OMITTED_ACTIVITY_DATE],
        "training_diagnostics": diagnostics,
        "note": (
            "These rates are computed on the same rows used to fit the pilot. "
            "They are not a validation score, not the 2023–2024 test, and not Reveal MODIS."
        ),
    }
    PILOT_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["probabilities"] = probabilities
    return report
