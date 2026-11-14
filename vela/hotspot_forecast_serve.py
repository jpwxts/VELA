"""Issue and serve Mindanao hotspot 24-hour forecasts (MODIS/VIIRS chance)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
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
from vela.grid import center, geographic_bounds
from vela.land_check import normalize_ring, point_in_ring, polygon_bbox
from vela.observation_store import ObservationStore, _connect as store_connect
from vela.settings import DATA_DIR

STORE_PATH = DATA_DIR / "observations" / "philippines_hotspot_forecasts.sqlite"
PUBLIC_LABEL = "Chance satellites record a hotspot in this square."
# Dry-season months that dominate Maguindanao v2.1 training (Feb/Mar) plus sparse Aug.
TRAIN_DISTRIBUTION_MONTHS = {2, 3, 8}
HIGH_PROB_EXPERIMENTAL_THRESHOLD = 0.9
HIGH_PROB_AUDIT_PATH = DATA_DIR / "metrics" / "philippines_hotspot_high_probability_audit.json"

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

    def delete_issues_after(self, ph_today: str) -> int:
        """Remove wrongly archived future Manila issue dates."""

        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM hotspot_issues WHERE issue_date_ph > ?",
                (str(ph_today)[:10],),
            )
            connection.commit()
            return int(cursor.rowcount or 0)

    def for_day(self, issue_date_ph: str) -> dict[str, dict]:
        """All preserved square forecasts for one Philippine issue date."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT cell_id, payload_json FROM hotspot_issues WHERE issue_date_ph = ?",
                (str(issue_date_ph)[:10],),
            ).fetchall()
        return {str(row["cell_id"]): json.loads(row["payload_json"]) for row in rows}


def philippine_today(now: datetime | None = None) -> str:
    from vela.onset_forecast import philippine_issue_date

    return str(philippine_issue_date(now))[:10]


def forecast_eligibility(
    *,
    cell_id: str,
    issue_date_ph: str,
    ph_today: str | None = None,
    selection: dict | None = None,
    support: dict | None = None,
    observation_store: ObservationStore | None = None,
    allow_historical_reconstruction: bool = False,
) -> dict[str, Any]:
    """Single eligibility check for square, month, map, and replay paths."""

    day = str(issue_date_ph)[:10]
    today = str(ph_today or philippine_today())[:10]
    sel = selection if selection is not None else load_selection()
    model_reason = forecast_unavailable_reason(sel)
    in_study = bool((support or {}).get("geographic_support", {}).get("in_study_region"))
    if support is None:
        in_study = cell_id in set(study_cells())

    if not in_study:
        return {
            "eligible": False,
            "calendar_state": "unsupported_location",
            "reason": (
                "Outside Maguindanao study box — hotspot-forecast percentages are not evaluated here. "
                "Satellite readings and weather remain available."
            ),
            "ph_today": today,
        }
    if day > today:
        return {
            "eligible": False,
            "calendar_state": "upcoming",
            "reason": "Upcoming — no issued percentage until that Philippine date.",
            "ph_today": today,
        }
    if model_reason:
        return {
            "eligible": False,
            "calendar_state": "insufficient_inputs",
            "reason": model_reason,
            "ph_today": today,
        }

    obs = observation_store or ObservationStore()
    firms_ok = firms_regional_query_ok(obs, day)
    # Live today: FIRMS feed must be queryable. Past reconstructions may proceed when the
    # model can still build issue-time features from archived detections / coverage.
    if day == today and not firms_ok:
        return {
            "eligible": False,
            "calendar_state": "insufficient_inputs",
            "reason": (
                f"Insufficient issue-time inputs for {day}: regional FIRMS query not OK "
                "(empty FIRMS is not treated as clear coverage)."
            ),
            "ph_today": today,
        }
    if day < today and not firms_ok and not allow_historical_reconstruction:
        # Still allow reconstruction when historical_simulation / month past path sets the flag,
        # but surface the specific FIRMS gap when neither archive nor reconstruction is requested.
        pass

    return {
        "eligible": True,
        "calendar_state": "forecast_available",
        "reason": None,
        "ph_today": today,
        "firms_regional_query_ok": firms_ok,
    }


def experimental_score_meta(probability: float, issue_date_ph: str, features: dict) -> dict[str, Any]:
    """Label high / OOD scores experimental without capping the displayed percentage."""

    month = date.fromisoformat(str(issue_date_ph)[:10]).month
    ood_month = month not in TRAIN_DISTRIBUTION_MONTHS
    high = float(probability) >= HIGH_PROB_EXPERIMENTAL_THRESHOLD
    sparse = float(features.get("coverage_days_7d") or 0.0) <= 0.0
    experimental = high or ood_month
    limitation = None
    if HIGH_PROB_AUDIT_PATH.is_file():
        try:
            limitation = json.loads(HIGH_PROB_AUDIT_PATH.read_text(encoding="utf-8")).get(
                "serving_policy", {}
            ).get("limitation_for_research")
        except json.JSONDecodeError:
            limitation = None
    if not limitation and experimental:
        limitation = (
            "High percentages are experimental outside dry-season training months and when "
            "local fire-mask coverage history is sparse."
        )
    return {
        "experimental": experimental,
        "experimental_reasons": [
            reason
            for reason, flag in (
                ("probability_ge_90_percent", high),
                ("month_outside_train_distribution", ood_month),
                ("sparse_local_fire_mask_coverage", sparse and high),
            )
            if flag
        ],
        "experimental_limitation": limitation if experimental else None,
    }


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


def _load_model_bundle(selection: dict) -> dict | None:
    artifact = selection.get("model_artifact") if selection else None
    if not artifact:
        return None
    path = Path(artifact)
    if not path.is_file():
        path = DATA_DIR / "models" / path.name
    if not path.is_file():
        return None
    bundle = joblib.load(path)
    if bundle.get("kind") == "baseline" and bundle.get("winner_name") != "persistence_recent_heat":
        comparison_path = Path(selection["comparison_path"])
        if not comparison_path.is_file():
            comparison_path = DATA_DIR / "metrics" / comparison_path.name
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        rate = comparison.get("row_counts", {}).get("positive_train", 0) / max(
            1, comparison.get("row_counts", {}).get("train", 1)
        )
        bundle = dict(bundle)
        bundle["global_rate"] = rate
    return bundle


def _decorate_score(payload: dict, probability: float, features: dict, issue_date_ph: str) -> dict:
    payload.update(experimental_score_meta(probability, issue_date_ph, features))
    payload["public_label"] = PUBLIC_LABEL
    return payload


def forecast_for_cell(
    *,
    cell_id: str,
    issue_date_ph: str | None = None,
    historical_simulation: bool = False,
    availability_delay_hours: float = 0.0,
    store: HotspotForecastStore | None = None,
    observation_store: ObservationStore | None = None,
    ph_today: str | None = None,
) -> dict[str, Any]:
    day = str(issue_date_ph or philippine_today())[:10]
    today = str(ph_today or philippine_today())[:10]
    selection = load_selection()
    obs = observation_store or ObservationStore()
    archive = store or HotspotForecastStore()
    archive.delete_issues_after(today)

    detections = load_study_detections(obs)
    support = _support_metadata(
        cell_id=cell_id,
        issue_date_ph=day,
        detections=detections,
        observation_store=obs,
    )
    eligibility = forecast_eligibility(
        cell_id=cell_id,
        issue_date_ph=day,
        ph_today=today,
        selection=selection,
        support=support,
        observation_store=obs,
        allow_historical_reconstruction=historical_simulation,
    )
    base = {
        "product": PRODUCT,
        "public_label": PUBLIC_LABEL,
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
        "ph_today": today,
        "eligibility": eligibility,
    }

    # Never serve or re-issue future Manila dates (even if a stale archive row existed).
    if eligibility["calendar_state"] == "upcoming":
        return {
            **base,
            "status": "upcoming",
            "probability": None,
            "probability_percent": None,
            "reason": eligibility["reason"],
            "calendar_state": "upcoming",
            "issuance_kind": None,
        }
    if eligibility["calendar_state"] == "unsupported_location":
        return {
            **base,
            "status": "unsupported",
            "probability": None,
            "probability_percent": None,
            "reason": eligibility["reason"],
            "calendar_state": "unsupported_location",
            "issuance_kind": None,
        }

    existing = archive.get(cell_id, day)
    if existing is not None and availability_delay_hours == 0 and day <= today:
        existing = dict(existing)
        existing["support"] = support
        existing["public_label"] = PUBLIC_LABEL
        existing["ph_today"] = today
        existing["eligibility"] = eligibility
        existing["outcome"] = archive.outcome(cell_id, day) or {
            "status": "awaiting_observation",
            "label": "Outcome awaiting observation",
        }
        existing["issuance_kind"] = "preserved_archive"
        existing["feature_cutoff_manila"] = support.get("input_cutoff_manila")
        existing["feature_cutoff_utc"] = support.get("input_cutoff_utc")
        existing["calendar_state"] = "forecast_available"
        feats = existing.get("features") or {}
        prob = existing.get("probability")
        if prob is not None:
            _decorate_score(existing, float(prob), feats if isinstance(feats, dict) else {}, day)
        if historical_simulation:
            existing["historical_simulation"] = False
            existing["label_note"] = (
                "Preserved forecast as originally issued — not a fresh historical reconstruction."
            )
        return existing

    if not eligibility["eligible"]:
        return {
            **base,
            "status": "unavailable",
            "probability": None,
            "probability_percent": None,
            "reason": eligibility["reason"],
            "calendar_state": eligibility["calendar_state"],
            "issuance_kind": None,
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
    bundle = _load_model_bundle(selection or {})
    if bundle is None:
        return {
            **base,
            "status": "unavailable",
            "probability": None,
            "probability_percent": None,
            "reason": "Model artifact unavailable",
            "calendar_state": "insufficient_inputs",
        }
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
        "feature_cutoff_manila": support.get("input_cutoff_manila"),
        "feature_cutoff_utc": support.get("input_cutoff_utc"),
    }
    _decorate_score(payload, probability, features, day)
    if historical_simulation:
        payload["historical_simulation"] = True
        payload["issuance_kind"] = "historical_reconstruction"
        payload["label_note"] = (
            "Historical reconstruction — not an originally issued Vela forecast unless a preserved "
            "issue archive entry exists for this square and date."
        )
        return payload
    # Live issue only for today (or past when explicitly requested without simulation).
    if day > today:
        payload["status"] = "upcoming"
        payload["probability"] = None
        payload["probability_percent"] = None
        payload["calendar_state"] = "upcoming"
        payload["issuance_kind"] = None
        return payload
    already = archive.get(cell_id, day)
    stored = archive.put_if_absent(payload)
    stored = dict(stored)
    stored["outcome"] = archive.outcome(cell_id, day) or {
        "status": "awaiting_observation",
        "label": "Outcome awaiting observation",
    }
    stored["support"] = support
    stored["public_label"] = PUBLIC_LABEL
    stored["ph_today"] = today
    stored["feature_cutoff_manila"] = support.get("input_cutoff_manila")
    stored["feature_cutoff_utc"] = support.get("input_cutoff_utc")
    stored["issuance_kind"] = "preserved_archive" if already is not None else "newly_issued"
    _decorate_score(stored, float(stored.get("probability") or probability), features, day)
    if already is None:
        stored["issued_at_utc"] = stored.get("issued_at_utc") or datetime.now(timezone.utc).isoformat()
    return stored


def month_forecasts_for_cell(
    cell_id: str,
    year_month: str,
    *,
    ph_today: str | None = None,
) -> dict[str, Any]:
    """Daily hotspot-forecast states for one square and YYYY-MM (calendar agreement)."""

    year_month = str(year_month)[:7]
    year, month = [int(part) for part in year_month.split("-")]
    from calendar import monthrange

    today = str(ph_today or philippine_today())[:10]
    days = monthrange(year, month)[1]
    archive = HotspotForecastStore()
    archive.delete_issues_after(today)
    selection = load_selection()
    obs = ObservationStore()
    detections = load_study_detections(obs)
    mask_info = fire_mask_coverage_keys(study_cells())
    coverage_days = {d for (_, d) in mask_info["square_days"]}
    bundle = _load_model_bundle(selection or {}) if selection else None
    in_study = cell_id in set(study_cells())

    rows = []
    for day_num in range(1, days + 1):
        day = f"{year:04d}-{month:02d}-{day_num:02d}"
        support = {
            "geographic_support": {"in_study_region": in_study, "study": STUDY, "cell_id": cell_id}
        }
        eligibility = forecast_eligibility(
            cell_id=cell_id,
            issue_date_ph=day,
            ph_today=today,
            selection=selection,
            support=support,
            observation_store=obs,
            allow_historical_reconstruction=True,
        )
        if eligibility["calendar_state"] == "upcoming":
            rows.append(
                {
                    "date": day,
                    "probability_percent": None,
                    "probability": None,
                    "model_version": None,
                    "calendar_state": "upcoming",
                    "issuance_kind": None,
                    "issue_time_manila": issue_datetime_manila(day).isoformat(),
                    "historical_simulation": False,
                    "reason": eligibility["reason"],
                    "label": "Upcoming",
                }
            )
            continue
        if eligibility["calendar_state"] == "unsupported_location":
            rows.append(
                {
                    "date": day,
                    "probability_percent": None,
                    "model_version": None,
                    "calendar_state": "unsupported_location",
                    "issuance_kind": None,
                    "issue_time_manila": issue_datetime_manila(day).isoformat(),
                    "reason": eligibility["reason"],
                }
            )
            continue

        existing = archive.get(cell_id, day) if day <= today else None
        if existing is not None:
            exp = experimental_score_meta(
                float(existing.get("probability") or 0.0),
                day,
                existing.get("features") or {},
            )
            rows.append(
                {
                    "date": day,
                    "probability_percent": existing.get("probability_percent"),
                    "probability": existing.get("probability"),
                    "model_version": existing.get("model_version"),
                    "calendar_state": "forecast_available",
                    "issuance_kind": "preserved_archive",
                    "issue_time_manila": existing.get("issue_time_manila"),
                    "issued_at_utc": existing.get("issued_at_utc"),
                    "feature_cutoff_manila": existing.get("feature_cutoff_manila")
                    or existing.get("issue_time_manila"),
                    "historical_simulation": False,
                    **exp,
                }
            )
            continue

        if not eligibility["eligible"] or bundle is None:
            rows.append(
                {
                    "date": day,
                    "probability_percent": None,
                    "model_version": None,
                    "calendar_state": "insufficient_inputs",
                    "issuance_kind": None,
                    "issue_time_manila": issue_datetime_manila(day).isoformat(),
                    "historical_simulation": True,
                    "reason": eligibility.get("reason") or "Model unavailable",
                }
            )
            continue

        features = build_feature_row(
            cell_id=cell_id,
            issue_date_ph=day,
            detections=detections,
            coverage_days=coverage_days,
        )
        probability = _predict_probability(bundle, features)
        percent = int(round(max(0.0, min(1.0, probability)) * 100))
        exp = experimental_score_meta(probability, day, features)
        rows.append(
            {
                "date": day,
                "probability_percent": percent,
                "probability": probability,
                "model_version": selection.get("chosen_model") if selection else None,
                "calendar_state": "forecast_available",
                "issuance_kind": "historical_reconstruction",
                "issue_time_manila": issue_datetime_manila(day).isoformat(),
                "feature_cutoff_manila": issue_datetime_manila(day).isoformat(),
                "historical_simulation": True,
                **exp,
            }
        )
    return {
        "cell_id": cell_id,
        "year_month": year_month,
        "ph_today": today,
        "public_label": PUBLIC_LABEL,
        "days": rows,
        "note": (
            "Issued archive rows for past/today Manila dates; labeled historical reconstructions "
            "for eligible past days without an archive; Upcoming for dates after Philippine today."
        ),
    }


def _overlay_cell(cell_id: str) -> dict[str, Any]:
    x_text, y_text = str(cell_id).split(":", 1)
    x_index, y_index = int(x_text), int(y_text)
    west, south, east, north = geographic_bounds(x_index, y_index)
    longitude, latitude = center(x_index, y_index)
    return {
        "cell_id": cell_id,
        "grid_x": x_index,
        "grid_y": y_index,
        "center": {"lon": longitude, "lat": latitude},
        "bounds": {"west": west, "south": south, "east": east, "north": north},
    }


def _cell_overlaps_ring(cell: dict[str, Any], ring: list[list[float]], ring_box: tuple[float, float, float, float]) -> bool:
    bounds = cell["bounds"]
    west, south, east, north = ring_box
    if bounds["east"] < west or bounds["west"] > east or bounds["north"] < south or bounds["south"] > north:
        return False
    if point_in_ring(float(cell["center"]["lon"]), float(cell["center"]["lat"]), ring):
        return True
    if any(bounds["west"] <= lon <= bounds["east"] and bounds["south"] <= lat <= bounds["north"] for lon, lat in ring):
        return True
    return any(
        point_in_ring(lon, lat, ring)
        for lon, lat in (
            (bounds["west"], bounds["south"]),
            (bounds["east"], bounds["south"]),
            (bounds["east"], bounds["north"]),
            (bounds["west"], bounds["north"]),
        )
    )


def probability_overlay(
    coordinates: list[list[float]],
    issue_date_ph: str | None = None,
    *,
    historical_simulation: bool = False,
    ph_today: str | None = None,
    observation_store: ObservationStore | None = None,
    store: HotspotForecastStore | None = None,
) -> dict[str, Any]:
    """Continuous 0–1 prediction surface for supported cells touching a boundary.

    This bulk path is read-only: it reuses preserved forecasts where available and
    scores the remaining cells without turning the selected polygon into one chance.
    """

    ring = normalize_ring(coordinates)
    day = str(issue_date_ph or philippine_today())[:10]
    today = str(ph_today or philippine_today())[:10]
    ring_box = polygon_bbox(ring)
    selected_cells = [
        cell
        for cell in (_overlay_cell(cell_id) for cell_id in study_cells())
        if _cell_overlaps_ring(cell, ring, ring_box)
    ]
    base = {
        "status": "ok",
        "issue_date_ph": day,
        "ph_today": today,
        "public_label": PUBLIC_LABEL,
        "probability_scale": {
            "kind": "continuous",
            "domain": [0.0, 1.0],
            "normalization": "none",
        },
        "polygon_probability": None,
        "cells": [],
    }
    if not selected_cells:
        return {
            **base,
            "status": "unsupported",
            "reason": "The selected boundary does not overlap the evaluated Maguindanao forecast area.",
            "extent": None,
            "highest_square": None,
        }
    if day > today:
        return {
            **base,
            "status": "upcoming",
            "reason": "Upcoming — no issued probability surface until that Philippine date.",
            "extent": None,
            "highest_square": None,
        }

    selection = load_selection()
    obs = observation_store or ObservationStore()
    eligibility = forecast_eligibility(
        cell_id=selected_cells[0]["cell_id"],
        issue_date_ph=day,
        ph_today=today,
        selection=selection,
        support={"geographic_support": {"in_study_region": True}},
        observation_store=obs,
        allow_historical_reconstruction=historical_simulation,
    )
    if not eligibility["eligible"]:
        return {
            **base,
            "status": "unavailable",
            "reason": eligibility["reason"],
            "extent": None,
            "highest_square": None,
        }
    bundle = _load_model_bundle(selection or {})
    if bundle is None:
        return {
            **base,
            "status": "unavailable",
            "reason": "Model artifact unavailable",
            "extent": None,
            "highest_square": None,
        }

    detections = load_study_detections(obs)
    coverage_days = {date_text for _, date_text in fire_mask_coverage_keys(study_cells())["square_days"]}
    archive = store or HotspotForecastStore()
    archived = archive.for_day(day)
    rows = []
    for cell in selected_cells:
        preserved = archived.get(cell["cell_id"])
        if preserved is not None and preserved.get("probability") is not None:
            probability = float(preserved["probability"])
            experimental = experimental_score_meta(
                probability,
                day,
                preserved.get("features") or {},
            )
            issuance_kind = "preserved_archive"
        else:
            features = build_feature_row(
                cell_id=cell["cell_id"],
                issue_date_ph=day,
                detections=detections,
                coverage_days=coverage_days,
            )
            probability = _predict_probability(bundle, features)
            experimental = experimental_score_meta(probability, day, features)
            issuance_kind = "historical_reconstruction" if day < today else "live_map_prediction"
        probability = max(0.0, min(1.0, float(probability)))
        rows.append(
            {
                **cell,
                "probability": probability,
                "probability_percent": int(round(probability * 100)),
                "issuance_kind": issuance_kind,
                "experimental": bool(experimental.get("experimental")),
            }
        )

    extent = {
        "west": min(row["bounds"]["west"] for row in rows),
        "south": min(row["bounds"]["south"] for row in rows),
        "east": max(row["bounds"]["east"] for row in rows),
        "north": max(row["bounds"]["north"] for row in rows),
    }
    highest = max(rows, key=lambda row: row["probability"])
    return {
        **base,
        "cells": rows,
        "extent": extent,
        "highest_square": {
            "cell_id": highest["cell_id"],
            "probability_percent": highest["probability_percent"],
        },
        "reason": None,
        "note": (
            "Each shade is a backend square prediction on a fixed 0–100% scale. "
            "Colors are interpolated only for display; no polygon-wide probability is calculated."
        ),
    }


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
