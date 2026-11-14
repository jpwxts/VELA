"""Issue and serve Mindanao hotspot 24-hour forecasts (MODIS/VIIRS chance)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from vela.hotspot_forecast import (
    FEATURE_NAMES,
    PRODUCT,
    SELECTION_PATH,
    STUDY,
    forecast_unavailable_reason,
    issue_datetime_manila,
    load_selection,
    valid_interval,
)
from vela.hotspot_forecast_dataset import build_feature_row, load_study_detections, regional_query_ok
from vela.observation_store import ObservationStore, _connect as store_connect
from vela.settings import DATA_DIR

STORE_PATH = DATA_DIR / "observations" / "philippines_hotspot_forecasts.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotspot_issues (
    issue_key TEXT PRIMARY KEY,
    cell_id TEXT NOT NULL,
    issue_date_ph TEXT NOT NULL,
    issued_at_utc TEXT NOT NULL,
    probability REAL,
    model_version TEXT,
    historical_simulation INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hotspot_issues_day ON hotspot_issues(issue_date_ph);
CREATE TABLE IF NOT EXISTS hotspot_outcomes (
    outcome_key TEXT PRIMARY KEY,
    cell_id TEXT NOT NULL,
    issue_date_ph TEXT NOT NULL,
    status TEXT NOT NULL,
    label TEXT NOT NULL,
    detection_count INTEGER,
    payload_json TEXT NOT NULL
);
"""


class HotspotForecastStore:
    def __init__(self, path: Path | None = None):
        self.path = path or STORE_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, cell_id: str, issue_date_ph: str) -> dict | None:
        key = f"{cell_id}|{issue_date_ph}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM hotspot_issues WHERE issue_key = ?", (key,)
            ).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    def put_if_absent(self, payload: dict) -> dict:
        cell_id = payload["cell_id"]
        issue_date_ph = payload["issue_date_ph"]
        existing = self.get(cell_id, issue_date_ph)
        if existing is not None:
            return existing
        key = f"{cell_id}|{issue_date_ph}"
        issued_at = payload.get("issued_at_utc") or datetime.now(timezone.utc).isoformat()
        stored = dict(payload)
        stored["issued_at_utc"] = issued_at
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO hotspot_issues (
                    issue_key, cell_id, issue_date_ph, issued_at_utc, probability,
                    model_version, historical_simulation, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    cell_id,
                    issue_date_ph,
                    issued_at,
                    payload.get("probability"),
                    payload.get("model_version"),
                    1 if payload.get("historical_simulation") else 0,
                    json.dumps(stored),
                ),
            )
            connection.commit()
        return self.get(cell_id, issue_date_ph) or stored

    def record_outcome(self, cell_id: str, issue_date_ph: str, status: str, label: str, detection_count: int = 0) -> dict:
        key = f"{cell_id}|{issue_date_ph}"
        payload = {
            "status": status,
            "label": label,
            "detection_count": detection_count,
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO hotspot_outcomes (
                    outcome_key, cell_id, issue_date_ph, status, label, detection_count, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (key, cell_id, issue_date_ph, status, label, detection_count, json.dumps(payload)),
            )
            connection.commit()
        return payload

    def outcome(self, cell_id: str, issue_date_ph: str) -> dict | None:
        key = f"{cell_id}|{issue_date_ph}"
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM hotspot_outcomes WHERE outcome_key = ?", (key,)
            ).fetchone()
        return None if row is None else json.loads(row["payload_json"])


def _predict_probability(bundle: dict, features: dict) -> float:
    values = []
    means = bundle.get("imputer_means") or [0.0] * len(FEATURE_NAMES)
    for index, name in enumerate(FEATURE_NAMES):
        raw = features.get(name)
        values.append(float(means[index]) if raw is None else float(raw))
    x = np.asarray([values], dtype=float)
    kind = bundle.get("kind")
    if kind == "baseline":
        if bundle.get("winner_name") == "persistence_recent_heat":
            return float(features.get("persistence_heat_yesterday") or 0.0)
        # seasonal baseline without full train table: use month prior from model meta if present
        return float(bundle.get("global_rate") or 0.0)
    model = bundle["model"]
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)
        return float(proba[0, 1] if proba.ndim == 2 else proba[0])
    scores = model.decision_function(x)
    return float(1.0 / (1.0 + np.exp(-scores[0])))


def forecast_for_cell(
    *,
    cell_id: str,
    issue_date_ph: str | None = None,
    historical_simulation: bool = False,
    store: HotspotForecastStore | None = None,
    observation_store: ObservationStore | None = None,
) -> dict[str, Any]:
    from vela.onset_forecast import philippine_issue_date

    day = str(issue_date_ph or philippine_issue_date())[:10]
    selection = load_selection()
    reason = forecast_unavailable_reason(selection)
    base = {
        "product": PRODUCT,
        "public_label": "Chance of satellite-detected heat",
        "question": (
            "For this 5 km square, what is the estimated chance that MODIS or VIIRS "
            "will detect heat in the next 24 hours?"
        ),
        "cell_id": cell_id,
        "issue_date_ph": day,
        "issue_time_manila": issue_datetime_manila(day).isoformat(),
        "valid_interval": valid_interval(day),
        "study": STUDY,
        "historical_simulation": historical_simulation,
    }
    if reason:
        return {
            **base,
            "status": "unavailable",
            "probability": None,
            "probability_percent": None,
            "reason": reason,
            "calendar_state": "insufficient_inputs",
        }

    archive = store or HotspotForecastStore()
    existing = archive.get(cell_id, day)
    if existing is not None and not historical_simulation:
        existing = dict(existing)
        existing["outcome"] = archive.outcome(cell_id, day) or {
            "status": "awaiting_observation",
            "label": "Outcome awaiting observation",
        }
        existing["calendar_state"] = "forecast_available"
        return existing

    obs = observation_store or ObservationStore()
    detections = load_study_detections(obs)
    with store_connect(obs.path) as connection:
        days = [row[0] for row in connection.execute("SELECT DISTINCT ph_date FROM feed_checks").fetchall()]
    coverage_days = {d for d in days if regional_query_ok(obs, d)}
    features = build_feature_row(
        cell_id=cell_id,
        issue_date_ph=day,
        detections=detections,
        coverage_days=coverage_days,
    )
    bundle = joblib.load(selection["model_artifact"])
    if bundle.get("kind") == "baseline" and bundle.get("winner_name") != "persistence_recent_heat":
        # Fall back to validation positive rate stored at train time if present
        comparison = json.loads(Path(selection["comparison_path"]).read_text(encoding="utf-8"))
        rate = comparison.get("row_counts", {}).get("positive_train", 0) / max(
            1, comparison.get("row_counts", {}).get("train", 1)
        )
        bundle = dict(bundle)
        bundle["global_rate"] = rate
    probability = _predict_probability(bundle, features)
    percent = int(round(max(0.0, min(1.0, probability)) * 100))
    payload = {
        **base,
        "status": "issued",
        "probability": probability,
        "probability_percent": percent,
        "model_version": selection.get("chosen_model"),
        "model_hash": selection.get("model_hash"),
        "features": features,
        "calendar_state": "forecast_available",
        "reason": None,
    }
    if historical_simulation:
        payload["historical_simulation"] = True
        payload["label_note"] = "Historical simulation — not an originally issued Vela forecast."
        return payload
    stored = archive.put_if_absent(payload)
    stored = dict(stored)
    stored["outcome"] = archive.outcome(cell_id, day) or {
        "status": "awaiting_observation",
        "label": "Outcome awaiting observation",
    }
    return stored


def polygon_hotspot_summary(cell_ids: list[str], issue_date_ph: str | None = None) -> dict:
    cells = [forecast_for_cell(cell_id=cid, issue_date_ph=issue_date_ph) for cid in cell_ids]
    issued = [row for row in cells if row.get("probability") is not None]
    highest = max(issued, key=lambda row: float(row["probability"])) if issued else None
    return {
        "cells": cells,
        "highest_square": None
        if highest is None
        else {
            "cell_id": highest["cell_id"],
            "probability_percent": highest["probability_percent"],
            "issue_time_manila": highest["issue_time_manila"],
        },
        "polygon_probability": None,
        "note": "Highest square percentage stays attached to that square; not a polygon-wide chance.",
    }
