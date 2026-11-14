"""Build onset training rows: labels × issue-time features × pre-fit split."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from vela.onset_features import build_issue_time_features
from vela.onset_forecast import FEATURE_NAMES, SPLIT_PATH, load_split
from vela.onset_labels import import_label_directory

SPLIT_RANK = {"train": 0, "validation": 1, "test": 2}


def _province_bucket(province: str | None, split: dict[str, Any]) -> str | None:
    if not province:
        return None
    geo = split.get("geographic_holdout") or {}
    name = province.strip().lower()
    for bucket, key in (
        ("train", "train_provinces_provisional"),
        ("validation", "validation_provinces_provisional"),
        ("test", "test_provinces_provisional"),
    ):
        for item in geo.get(key) or []:
            if str(item).strip().lower() == name:
                return bucket
    return None


def _temporal_bucket(issue_date_ph: str) -> str:
    day = date.fromisoformat(issue_date_ph[:10])
    if day <= date(2023, 12, 31):
        return "train"
    if day <= date(2024, 12, 31):
        return "validation"
    return "test"


def assign_split(row: dict[str, Any], split: dict[str, Any]) -> str:
    """Combine temporal and geographic rules; take the more holdout-restrictive bucket."""

    temporal = _temporal_bucket(row["issue_date_ph"])
    geographic = _province_bucket(row.get("province"), split)
    if geographic is None:
        return temporal
    if SPLIT_RANK[geographic] >= SPLIT_RANK[temporal]:
        return geographic
    return temporal


def _impute_fit(matrix: np.ndarray) -> dict[str, float]:
    means = []
    for col in range(matrix.shape[1]):
        values = matrix[:, col]
        finite = values[np.isfinite(values)]
        means.append(float(np.mean(finite)) if len(finite) else 0.0)
    return {"means": means}


def _impute_transform(matrix: np.ndarray, stats: dict[str, float]) -> np.ndarray:
    out = matrix.copy()
    means = stats["means"]
    for col, mean in enumerate(means):
        mask = ~np.isfinite(out[:, col])
        out[mask, col] = mean
    return out


def build_feature_matrix(
    labeled_rows: list[dict[str, Any]],
    *,
    detections_by_day: dict[str, list[dict]] | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    detections_by_day = detections_by_day or {}
    feature_rows = []
    matrix = []
    for row in labeled_rows:
        day = row["issue_date_ph"]
        detections = []
        stamp = date.fromisoformat(day)
        for offset in (-2, -1, 0):
            key = (stamp + timedelta(days=offset)).isoformat()
            detections.extend(detections_by_day.get(key) or [])
        features = build_issue_time_features(
            cell_id=row["cell_id"],
            issue_date_ph=day,
            detections=detections,
            weather_forecast=None,
            rainfall_history=None,
        )
        values = []
        for name in FEATURE_NAMES:
            raw = features["values"].get(name)
            values.append(float(raw) if raw is not None else np.nan)
        matrix.append(values)
        feature_rows.append(
            {
                **row,
                "missing_features": features["missing_features"],
                "reduced_feature_baseline": features["reduced_feature_baseline"],
                "feature_values": features["values"],
            }
        )
    return np.asarray(matrix, dtype=float), feature_rows


def build_dataset(
    label_dir: Path,
    *,
    split_path: Path | None = None,
    detections_by_day: dict[str, list[dict]] | None = None,
) -> dict[str, Any]:
    split = load_split(split_path or SPLIT_PATH)
    imported = import_label_directory(label_dir)
    labeled = imported.labeled_square_days
    # Incident-level leakage control: all rows sharing incident_id share the strictest split.
    incident_splits: dict[str, str] = {}
    provisional = []
    for row in labeled:
        bucket = assign_split(row, split)
        provisional.append({**row, "split": bucket})
        incident_id = row.get("incident_id")
        if incident_id:
            previous = incident_splits.get(incident_id)
            if previous is None or SPLIT_RANK[bucket] > SPLIT_RANK[previous]:
                incident_splits[incident_id] = bucket
    rows = []
    for row in provisional:
        incident_id = row.get("incident_id")
        if incident_id and incident_id in incident_splits:
            row = {**row, "split": incident_splits[incident_id]}
        rows.append(row)

    x_raw, feature_rows = build_feature_matrix(rows, detections_by_day=detections_by_day)
    for index, row in enumerate(feature_rows):
        row["split"] = rows[index]["split"]

    by_split = {"train": [], "validation": [], "test": []}
    for index, row in enumerate(feature_rows):
        by_split[row["split"]].append(index)

    train_idx = np.asarray(by_split["train"], dtype=int)
    valid_idx = np.asarray(by_split["validation"], dtype=int)
    test_idx = np.asarray(by_split["test"], dtype=int)

    imputer = None
    x_train = x_valid = x_test = np.zeros((0, len(FEATURE_NAMES)))
    y_train = y_valid = y_test = np.zeros((0,), dtype=int)
    if len(train_idx):
        imputer = _impute_fit(x_raw[train_idx])
        x_train = _impute_transform(x_raw[train_idx], imputer)
        y_train = np.asarray([feature_rows[i]["label"] for i in train_idx], dtype=int)
    if len(valid_idx) and imputer is not None:
        x_valid = _impute_transform(x_raw[valid_idx], imputer)
        y_valid = np.asarray([feature_rows[i]["label"] for i in valid_idx], dtype=int)
    if len(test_idx) and imputer is not None:
        x_test = _impute_transform(x_raw[test_idx], imputer)
        y_test = np.asarray([feature_rows[i]["label"] for i in test_idx], dtype=int)

    def season_key(row: dict) -> str:
        month = int(str(row["issue_date_ph"])[5:7])
        province = row.get("province") or "unknown"
        season = "dry" if month in {1, 2, 3, 4, 11, 12} else "wet"
        return f"{province}|{season}"

    return {
        "import_summary": imported.summary(),
        "split_manifest": split,
        "rows": feature_rows,
        "feature_names": FEATURE_NAMES,
        "imputer": imputer,
        "train": {
            "indices": train_idx.tolist(),
            "x": x_train,
            "y": y_train,
            "season_keys": [season_key(feature_rows[i]) for i in train_idx],
            "rows": [feature_rows[i] for i in train_idx],
        },
        "validation": {
            "indices": valid_idx.tolist(),
            "x": x_valid,
            "y": y_valid,
            "season_keys": [season_key(feature_rows[i]) for i in valid_idx],
            "rows": [feature_rows[i] for i in valid_idx],
        },
        "test": {
            "indices": test_idx.tolist(),
            "x": x_test,
            "y": y_test,
            "season_keys": [season_key(feature_rows[i]) for i in test_idx],
            "rows": [feature_rows[i] for i in test_idx],
        },
        "row_counts": {
            "train": int(len(train_idx)),
            "validation": int(len(valid_idx)),
            "test": int(len(test_idx)),
            "labeled_total": len(feature_rows),
            "positives": sum(1 for row in feature_rows if row["label"] == 1),
            "negatives": sum(1 for row in feature_rows if row["label"] == 0),
        },
    }


def write_split_counts(dataset: dict[str, Any], path: Path) -> dict[str, Any]:
    """Update split manifest row counts from actual labeled inputs (rules unchanged)."""

    split = dict(dataset["split_manifest"])
    counts = dataset["row_counts"]
    split["row_counts"] = {
        "train": counts["train"],
        "validation": counts["validation"],
        "test": counts["test"],
        "labeled_total": counts["labeled_total"],
        "positives": counts["positives"],
        "negatives": counts["negatives"],
        "reason": None
        if counts["labeled_total"]
        else "No usable unique wildfire starts or credible negative square-days.",
    }
    split["status"] = (
        "manifest_populated"
        if counts["labeled_total"]
        else "manifest_ready_labels_absent"
    )
    path.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    return split
