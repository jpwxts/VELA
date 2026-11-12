"""Audit the frozen logistic candidate. This does not refit or replace any artifact."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from vela.features import FEATURE_COLUMNS
from vela.settings import DATA_DIR, settings
from vela.train import MODEL_ORDER, _prepare, _probabilities, score_frozen_pipelines, selection_frame

WEEKS = (
    ("cerrado", "2021-02-22", "2021-02-28"),
    ("california", "2021-03-22", "2021-03-28"),
    ("zambia", "2021-07-19", "2021-07-25"),
)
AUDIT = DATA_DIR / "catalog" / "logistic_candidate_audit.json"


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = np.exp(-value)
        return float(1.0 / (1.0 + z))
    z = np.exp(value)
    return float(z / (1.0 + z))


def _positive_column(model) -> int:
    classes = [bool(item) if isinstance(item, (bool, np.bool_)) else item for item in model.classes_]
    for index, label in enumerate(model.classes_):
        if label == 1 or label is True or label == np.True_:
            return index
    raise RuntimeError(f"No MODIS-positive class in {list(model.classes_)}")


def _ranges(frame: pd.DataFrame) -> dict:
    columns = list(FEATURE_COLUMNS)
    values = frame.loc[:, columns]
    return {
        name: {
            "min": None if values[name].isna().all() else float(np.nanmin(values[name])),
            "max": None if values[name].isna().all() else float(np.nanmax(values[name])),
            "median": None if values[name].isna().all() else float(np.nanmedian(values[name])),
            "missing": int(values[name].isna().sum()),
        }
        for name in columns
    }


def main() -> int:
    artifact = joblib.load(DATA_DIR / "models" / "candidate_logistic_regression.joblib")
    pipeline = artifact["pipeline"]
    model = pipeline.named_steps["model"]
    imputer = pipeline.named_steps["imputer"]
    scaler = pipeline.named_steps["scaler"]
    positive = _positive_column(model)
    steps = [name for name, _step in pipeline.steps]
    frame = pd.read_parquet(DATA_DIR / "processed" / "paired_cells.parquet")
    prepared = _prepare(frame, settings())
    tune = selection_frame(prepared)
    train = prepared[(prepared["role"] == "train") & (prepared["split"] == "train")]
    labels = train["modis_detected"].astype(int).to_numpy()
    positive_rate = float(labels.mean())
    class_counts = {int(label): int((labels == label).sum()) for label in model.classes_}
    balanced_weights = {
        int(label): float(len(labels) / (len(model.classes_) * class_counts[int(label)]))
        for label in model.classes_
    }
    features = list(FEATURE_COLUMNS)
    stored_features = list(artifact.get("feature_columns") or [])
    hotspot = train["viirs_fire_low"] + train["viirs_fire_nominal"] + train["viirs_fire_high"]
    weeks = []
    trace = None
    for region_id, start, end in WEEKS:
        dates = tune["local_date"]
        part = tune[(tune["region_id"] == region_id) & (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))].copy()
        scored = score_frozen_pipelines(part, {"raw_viirs": None, "logistic_regression": pipeline, "random_forest": pipeline}, artifact["training_regions"])
        week = scored["weeks"][0]
        matrix = part.loc[:, features]
        coded = pipeline.predict_proba(matrix)
        column = coded[:, positive]
        scoring_column = _probabilities("logistic_regression", pipeline, part)
        quiet = part["viirs_hotspot_pixels"].to_numpy(dtype=float) < 1
        order = np.argsort(-column)
        chosen = part.iloc[int(order[0])]
        raw_frame = chosen.loc[list(features)].to_frame().T
        raw_frame.columns = features
        transformed = pipeline[:-1].transform(raw_frame)
        scaled = np.asarray(transformed, dtype=float)
        linear = float(model.decision_function(scaled)[0])
        raw = raw_frame.to_numpy(dtype=float)
        imputed = np.asarray(imputer.transform(raw_frame), dtype=float)
        record = {
            "region_id": region_id,
            "scoring_code_estimate": week["estimates"]["logistic_regression"],
            "mean_positive_class_probability": float(column.mean()),
            "scoring_column_matches_positive_class": bool(np.allclose(scoring_column, column)),
            "rows": int(len(part)),
            "zero_viirs_fire_pixel_rows": int(quiet.sum()),
            "mean_probability_when_zero_viirs_fire_pixels": float(column[quiet].mean()) if quiet.any() else None,
            "observed_modis_rate": week["observed_modis_rate"],
        }
        weeks.append(record)
        if region_id == "cerrado":
            contributions = [
                {"feature": name, "raw": float(raw[0, index]), "imputed": float(imputed[0, index]), "scaled": float(scaled[0, index]), "coefficient": float(model.coef_[0, index]), "contribution": float(model.coef_[0, index] * scaled[0, index])}
                for index, name in enumerate(features)
            ]
            contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
            trace = {
                "region_id": "cerrado",
                "local_date": str(chosen["local_date"])[:10],
                "cell_id": chosen["cell_id"],
                "viirs_hotspot_pixels": float(chosen["viirs_hotspot_pixels"]),
                "modis_detected": bool(chosen["modis_detected"]),
                "predicted_positive_probability": float(column[int(order[0])]),
                "linear_predictor": linear,
                "sigmoid_of_linear_predictor": _sigmoid(linear),
                "largest_contributions": contributions[:6],
            }
    report = {
        "label": "logistic candidate audit",
        "validation_label": "validation",
        "models_refit": False,
        "artifacts_replaced": False,
        "classes": [int(item) if isinstance(item, (int, np.integer)) else str(item) for item in model.classes_],
        "positive_class": int(model.classes_[positive]) if isinstance(model.classes_[positive], (int, np.integer)) else str(model.classes_[positive]),
        "positive_probability_column": positive,
        "scoring_uses_column_index_1": True,
        "feature_names_in_order": features,
        "artifact_feature_names": stored_features,
        "feature_order_matches_artifact": features == stored_features,
        "pipeline_steps": steps,
        "imputer": {"strategy": imputer.strategy, "statistics": [None if np.isnan(value) else float(value) for value in imputer.statistics_]},
        "scaler": {
            "with_mean": bool(scaler.with_mean),
            "with_std": bool(scaler.with_std),
            "mean": [float(value) for value in scaler.mean_],
            "scale": [float(value) for value in scaler.scale_],
        },
        "coefficients": {name: float(value) for name, value in zip(features, model.coef_[0])},
        "intercept": float(model.intercept_[0]),
        "probability_at_training_mean": _sigmoid(float(model.intercept_[0])),
        "training_rows": int(len(train)),
        "training_positives": int(train["modis_detected"].astype(bool).sum()),
        "training_positive_rate": positive_rate,
        "class_weight": model.class_weight,
        "balanced_weights_from_training_counts": balanced_weights,
        "training_class_counts": class_counts,
        "resampling": None,
        "duplicate_pipeline_steps": len(steps) != len(set(steps)),
        "hotspot_pixels_equal_fire_class_sum_on_training_rows": bool(np.allclose(train["viirs_hotspot_pixels"], hotspot)),
        "training_feature_ranges": _ranges(train),
        "validation_feature_ranges": _ranges(tune),
        "weeks": weeks,
        "cerrado_high_probability_row": trace,
        "reserved_not_scored": ["2023-2024", "pantanal"],
        "scoring_bug": not all(item["scoring_column_matches_positive_class"] for item in weeks),
    }
    report["performance"] = (
        "observed"
        if not report["scoring_bug"]
        else "scoring bug"
    )
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("classes", "positive_class", "positive_probability_column", "pipeline_steps", "intercept", "probability_at_training_mean", "training_positive_rate", "class_weight", "balanced_weights_from_training_counts", "scoring_bug")}, indent=2))
    for item in weeks:
        print(item["region_id"], "code", item["scoring_code_estimate"], "mean", item["mean_positive_class_probability"], "zero_rows", item["zero_viirs_fire_pixel_rows"], "zero_mean", item["mean_probability_when_zero_viirs_fire_pixels"])
    print("trace", trace["local_date"], trace["cell_id"], trace["predicted_positive_probability"], trace["largest_contributions"][:3])
    print(AUDIT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
