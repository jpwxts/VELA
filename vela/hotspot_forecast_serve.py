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
    STUDY,
    forecast_unavailable_reason,
    issue_datetime_manila,
    load_selection,
    valid_interval,
)
from vela.hotspot_forecast_dataset import (
    build_feature_row,
    fire_mask_coverage_keys,
    firms_regional_query_ok,
    load_study_detections,
    study_cells,
)
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

    def record_outcome(
        self, cell_id: str, issue_date_ph: str, status: str, label: str, detection_count: int = 0
    ) -> dict:
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
        return float(bundle.get("global_rate") or 0.0)
    model = bundle["model"]
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)
        return float(proba[0, 1] if proba.ndim == 2 else proba[0])
    scores = model.decision_function(x)
    return float(1.0 / (1.0 + np.exp(-scores[0])))


def _support_metadata(
    *,
    cell_id: str,
    issue_date_ph: str,
    detections: list[dict],
    observation_store: ObservationStore,
) -> dict[str, Any]:
    issue = issue_datetime_manila(issue_date_ph)
    issue_utc = issue.astimezone(timezone.utc)
    prior = [spot for spot in detections if spot["_acq_utc"] < issue_utc]
    newest = max((spot["_acq_utc"] for spot in prior), default=None)
    cell_prior = [spot for spot in prior if spot.get("_cell_id") == cell_id]
    newest_cell = max((spot["_acq_utc"] for spot in cell_prior), default=None)
    mask = fire_mask_coverage_keys([cell_id])
    in_study = cell_id in set(study_cells())
    firms_ok = firms_regional_query_ok(observation_store, issue_date_ph)
    return {
        "geographic_support": {
            "in_study_region": in_study,
            "study": STUDY,
            "cell_id": cell_id,
        },
        "input_cutoff_utc": issue_utc.isoformat(),
        "input_cutoff_manila": issue.isoformat(),
        "newest_available_input_utc": None if newest is None else newest.isoformat(),
        "newest_cell_detection_utc": None if newest_cell is None else newest_cell.isoformat(),
        "prior_detection_count_study": len(prior),
        "prior_detection_count_cell": len(cell_prior),
        "firms_regional_query_ok": firms_ok,
        "firms_empty_is_not_clear_coverage": True,
        "fire_mask_coverage_for_cell": mask["count"] > 0,
        "fire_mask_coverage_square_days_study": mask["count"],
        "availability_assumption": "acquisition≈availability unless a publication delay is applied",
    }


def forecast_for_cell(
    *,
    cell_id: str,
    issue_date_ph: str | None = None,
    historical_simulation: bool = False,
    availability_delay_hours: float = 0.0,
    store: HotspotForecastStore | None = None,
    observation_store: ObservationStore | None = None,
) -> dict[str, Any]:
    from vela.onset_forecast import philippine_issue_date

    day = str(issue_date_ph or philippine_issue_date())[:10]
    selection = load_selection()
    reason = forecast_unavailable_reason(selection)
    obs = observation_store or ObservationStore()
    detections = load_study_detections(obs)
    support = _support_metadata(
        cell_id=cell_id,
        issue_date_ph=day,
        detections=detections,
        observation_store=obs,
    )
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
        "support": support,
        "availability_delay_hours": float(availability_delay_hours),
    }
    archive = store or HotspotForecastStore()
    existing = archive.get(cell_id, day)
    # Preserved issued forecasts remain readable even when new serving is blocked.
    if existing is not None and availability_delay_hours == 0:
        existing = dict(existing)
        existing["support"] = support
        existing["outcome"] = archive.outcome(cell_id, day) or {
            "status": "awaiting_observation",
            "label": "Outcome awaiting observation",
        }
        if historical_simulation:
            existing["historical_simulation"] = False
            existing["label_note"] = (
                "Preserved forecast as originally issued — not a fresh historical simulation."
            )
            existing["calendar_state"] = "forecast_available"
            return existing
        if not reason:
            existing["calendar_state"] = "forecast_available"
            return existing

    if reason:
        return {
            **base,
            "status": "unavailable",
            "probability": None,
            "probability_percent": None,
            "reason": reason,
            "calendar_state": "insufficient_inputs",
        }

    mask_info = fire_mask_coverage_keys(study_cells())
    coverage_days = {d for (_, d) in mask_info["square_days"]}
    features = build_feature_row(
        cell_id=cell_id,
        issue_date_ph=day,
        detections=detections,
        coverage_days=coverage_days,
        availability_delay_hours=availability_delay_hours,
    )
    bundle = joblib.load(selection["model_artifact"])
    if bundle.get("kind") == "baseline" and bundle.get("winner_name") != "persistence_recent_heat":
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
        payload["label_note"] = (
            "Historical simulation — not an originally issued Vela forecast unless a preserved "
            "issue archive entry exists for this square and date."
        )
        return payload
    stored = archive.put_if_absent(payload)
    stored = dict(stored)
    stored["outcome"] = archive.outcome(cell_id, day) or {
        "status": "awaiting_observation",
        "label": "Outcome awaiting observation",
    }
    stored["support"] = support
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
