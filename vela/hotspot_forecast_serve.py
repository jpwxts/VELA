"""Issue and serve Mindanao hotspot 24-hour forecasts (MODIS/VIIRS chance)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from vela.hotspot_forecast import (
    COMPARISON_PATH,
    FEATURE_NAMES,
    FIRMS_REFRESH_STATUS_PATH,
    MAGUINDANAO_EVALUATED,
    MODELS_DIR,
    PRODUCT,
    STUDY,
    forecast_unavailable_reason,
    issue_datetime_manila,
    load_selection,
    valid_interval,
)
from vela.hotspot_forecast_dataset import (
    build_feature_row,
    evaluated_cells,
    fire_mask_coverage_keys,
    firms_regional_query_ok,
    load_study_detections,
    study_cells,
)
from vela.grid import cell_identifier, center, geographic_bounds, indices
from vela.land_check import normalize_ring, point_in_ring, polygon_bbox
from vela.observation_store import ObservationStore, _connect as store_connect
from vela.settings import DATA_DIR, WRITABLE_DATA_DIR

STORE_PATH = WRITABLE_DATA_DIR / "observations" / "philippines_hotspot_forecasts.sqlite"
PUBLIC_LABEL = "Chance satellites record a hotspot in this square in the next 24 hours."
# Dry-season months that dominate Maguindanao v2.1 training (Feb/Mar) plus sparse Aug.
TRAIN_DISTRIBUTION_MONTHS = {2, 3, 8}
HIGH_PROB_EXPERIMENTAL_THRESHOLD = 0.9
HIGH_PROB_AUDIT_PATH = DATA_DIR / "metrics" / "philippines_hotspot_high_probability_audit.json"
BOARD_MANIFEST_PATH = MODELS_DIR / "board_manifest.json"
_STUDY_SET: set[str] | None = None
_EVAL_SET: set[str] | None = None
_BOARD_CACHE: list[dict] | None = None
_COVERAGE_DAYS_CACHE: set[str] | None = None


def _study_set() -> set[str]:
    global _STUDY_SET
    if _STUDY_SET is None:
        _STUDY_SET = set(study_cells())
    return _STUDY_SET


def _eval_set() -> set[str]:
    global _EVAL_SET
    if _EVAL_SET is None:
        _EVAL_SET = set(evaluated_cells())
    return _EVAL_SET


def load_firms_refresh_status() -> dict | None:
    if not FIRMS_REFRESH_STATUS_PATH.is_file():
        return None
    try:
        return json.loads(FIRMS_REFRESH_STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def evaluation_context(selection: dict | None = None) -> dict[str, Any]:
    """Holdout accuracy/Brier context — never the day's percentage as accuracy."""

    sel = selection if selection is not None else load_selection()
    comparison = None
    if COMPARISON_PATH.is_file():
        try:
            comparison = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            comparison = None
    holdout = (comparison or {}).get("holdout") or {}
    claimable = holdout.get("claimable_ex_v22_reserve") or holdout.get("metrics") or {}
    winner = (comparison or {}).get("winner") or {}
    return {
        "note": (
            "Evaluation metrics are claimable holdout scores for the selected Maguindanao v2.1 "
            "model. They are not the accuracy of today's percentage for this square."
        ),
        "selected_model": (sel or {}).get("chosen_model") or winner.get("name"),
        "coverage_rule_version": (sel or {}).get("coverage_rule_version")
        or (comparison or {}).get("coverage_rule_version"),
        "claimable_holdout": {
            "n": claimable.get("n"),
            "positives": claimable.get("positives") or claimable.get("positive_event_count"),
            "accuracy": claimable.get("accuracy"),
            "brier_score": claimable.get("brier_score"),
            "precision": claimable.get("precision"),
            "recall": claimable.get("recall"),
            "f1": claimable.get("f1"),
        },
        "validation_brier": (winner.get("validation_metrics") or {}).get("brier_score"),
        "percentage_zone": MAGUINDANAO_EVALUATED,
        "study": STUDY,
    }


def _load_board_entries() -> list[dict]:
    """Load all persisted classifier/baseline board artifacts (six + baselines)."""

    global _BOARD_CACHE
    if _BOARD_CACHE is not None:
        return _BOARD_CACHE
    entries: list[dict] = []
    if BOARD_MANIFEST_PATH.is_file():
        try:
            manifest = json.loads(BOARD_MANIFEST_PATH.read_text(encoding="utf-8"))
            for row in manifest.get("models") or []:
                path = Path(row.get("artifact") or "")
                if not path.is_file():
                    continue
                bundle = joblib.load(path)
                entries.append(
                    {
                        "name": row.get("name") or bundle.get("winner_name"),
                        "kind": row.get("kind") or bundle.get("kind") or "classifier",
                        "artifact": str(path),
                        "bundle": bundle,
                        "validation_metrics": row.get("validation_metrics"),
                    }
                )
        except (json.JSONDecodeError, OSError):
            entries = []
    if not entries:
        # Fallback: winner-only until board export is run.
        selection = load_selection() or {}
        bundle = _load_model_bundle(selection)
        if bundle is not None:
            entries.append(
                {
                    "name": selection.get("chosen_model") or bundle.get("winner_name"),
                    "kind": bundle.get("kind") or "classifier",
                    "artifact": selection.get("model_artifact"),
                    "bundle": bundle,
                    "validation_metrics": None,
                }
            )
    _BOARD_CACHE = entries
    return entries


def build_model_board(features: dict, *, selection: dict | None = None) -> dict[str, Any]:
    """Probabilities from each saved classifier/baseline for past/today panels."""

    selected = (selection or load_selection() or {}).get("chosen_model")
    rows = []
    for entry in _load_board_entries():
        probability = _predict_probability(entry["bundle"], features)
        percent = int(round(max(0.0, min(1.0, probability)) * 100))
        metrics = entry.get("validation_metrics") or {}
        rows.append(
            {
                "name": entry["name"],
                "kind": entry["kind"],
                "probability": probability,
                "probability_percent": percent,
                "is_selected": entry["name"] == selected,
                "validation_accuracy": metrics.get("accuracy"),
                "validation_brier": metrics.get("brier_score"),
            }
        )
    rows.sort(key=lambda row: (0 if row.get("is_selected") else 1, row.get("name") or ""))
    return {
        "models": rows,
        "evaluation": evaluation_context(selection),
        "headline": selected,
        "note": (
            "Board lists each saved classifier/baseline probability for this square-day. "
            "The selected model remains the calendar headline. Validation accuracy/Brier are "
            "evaluation context, not this day's correctness."
        ),
    }

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
    geo = (support or {}).get("geographic_support") or {}
    in_study = bool(geo.get("in_study_region"))
    percentage_ok = bool(geo.get("percentage_supported"))
    if support is None:
        in_study = cell_id in _study_set()
        percentage_ok = cell_id in _eval_set()

    if not in_study:
        return {
            "eligible": False,
            "calendar_state": "unsupported_location",
            "reason": (
                "Outside Mindanao — hotspot-forecast percentages are not evaluated here. "
                "Satellite readings and weather remain available."
            ),
            "ph_today": today,
            "in_study_region": False,
            "percentage_supported": False,
        }
    if day > today:
        return {
            "eligible": False,
            "calendar_state": "upcoming",
            "reason": "Upcoming — no issued percentage until that Philippine date.",
            "ph_today": today,
            "in_study_region": True,
            "percentage_supported": percentage_ok,
        }
    if not percentage_ok:
        return {
            "eligible": False,
            "calendar_state": "coverage_status_only",
            "reason": (
                "Inside Mindanao, but outside the Maguindanao v2.1 evaluated box. "
                "Satellite readings, weather, and coverage status are available; "
                "percentages wait for island-wide clear-pass evaluation."
            ),
            "ph_today": today,
            "in_study_region": True,
            "percentage_supported": False,
        }
    if model_reason:
        return {
            "eligible": False,
            "calendar_state": "insufficient_inputs",
            "reason": model_reason,
            "ph_today": today,
            "in_study_region": True,
            "percentage_supported": True,
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
            "in_study_region": True,
            "percentage_supported": True,
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
        "in_study_region": True,
        "percentage_supported": True,
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
    in_study = cell_id in _study_set()
    percentage_ok = cell_id in _eval_set()
    firms_ok = firms_regional_query_ok(observation_store, issue_date_ph)
    firms_refresh = load_firms_refresh_status()
    return {
        "geographic_support": {
            "in_study_region": in_study,
            "percentage_supported": percentage_ok,
            "study": STUDY,
            "percentage_zone": MAGUINDANAO_EVALUATED,
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
        "firms_refresh": firms_refresh,
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


def _decorate_score(
    payload: dict,
    probability: float,
    features: dict,
    issue_date_ph: str,
    *,
    selection: dict | None = None,
    include_board: bool = False,
) -> dict:
    payload.update(experimental_score_meta(probability, issue_date_ph, features))
    payload["public_label"] = PUBLIC_LABEL
    payload["evaluation"] = evaluation_context(selection)
    if include_board and features:
        payload["model_board"] = build_model_board(features, selection=selection)
    return payload


def _coverage_days_cached() -> set[str]:
    """Coverage days for Maguindanao evaluated cells (feature builders)."""

    global _COVERAGE_DAYS_CACHE
    if _COVERAGE_DAYS_CACHE is None:
        mask_info = fire_mask_coverage_keys(evaluated_cells())
        _COVERAGE_DAYS_CACHE = {d for (_, d) in mask_info["square_days"]}
    return _COVERAGE_DAYS_CACHE


def _timely_selected_issue(payload: dict | None, selection: dict, day: str) -> bool:
    """An issue must precede its target window and match the approved candidate."""
    if not payload or payload.get("historical_simulation"):
        return False
    if payload.get("model_hash") != selection.get("model_hash"):
        return False
    if payload.get("model_version") != selection.get("chosen_model"):
        return False
    try:
        created = datetime.fromisoformat(str(payload["issued_at_utc"]).replace("Z", "+00:00"))
        cutoff = issue_datetime_manila(day)
        probability = float(payload["probability"])
        return created <= cutoff and 0 <= probability <= 1
    except (KeyError, TypeError, ValueError):
        return False


def forecast_for_cell(
    *, cell_id: str, issue_date_ph: str | None = None,
    historical_simulation: bool = False, availability_delay_hours: float = 0.0,
    store: HotspotForecastStore | None = None,
    observation_store: ObservationStore | None = None, ph_today: str | None = None,
) -> dict[str, Any]:
    """Read-only public serving. Research scores never become issued forecasts here."""
    day = str(issue_date_ph or philippine_today())[:10]
    today = str(ph_today or philippine_today())[:10]
    selection = load_selection() or {}
    support = {"geographic_support": {
        "in_study_region": cell_id in _study_set(),
        "percentage_supported": cell_id in _eval_set(),
        "study": STUDY, "percentage_zone": MAGUINDANAO_EVALUATED, "cell_id": cell_id,
    }}
    eligibility = forecast_eligibility(
        cell_id=cell_id, issue_date_ph=day, ph_today=today, selection=selection,
        support=support, observation_store=observation_store,
    )
    state = eligibility["calendar_state"]
    base = {
        "product": PRODUCT, "public_label": PUBLIC_LABEL, "cell_id": cell_id,
        "issue_date_ph": day, "issue_time_manila": None, "valid_interval": valid_interval(day),
        "study": MAGUINDANAO_EVALUATED, "support": support, "eligibility": eligibility,
        "ph_today": today, "probability": None, "probability_percent": None,
        "calendar_state": state, "issuance_kind": None, "historical_simulation": False,
        "reason": eligibility["reason"],
    }
    if not eligibility["eligible"]:
        status = {"upcoming": "upcoming", "unsupported_location": "unsupported",
                  "coverage_status_only": "coverage_status_only"}.get(state, "unavailable")
        return {**base, "status": status}
    existing = (store or HotspotForecastStore()).get(cell_id, day)
    if not _timely_selected_issue(existing, selection, day):
        return {**base, "status": "unavailable", "calendar_state": "not_issued",
                "reason": "No timely issued forecast from the approved model is archived for this square-day."}
    return {**base, **existing, "status": "issued", "calendar_state": "forecast_available",
            "issuance_kind": "preserved_archive", "reason": None,
            "probability_percent": round(float(existing["probability"]) * 100),
            "model_board": None,
            "meaning": "Among comparable covered square-days assigned this percentage, this fraction should have satellite-detected heat within the stated window. It is not a wildfire probability."}


def month_forecasts_for_cell(cell_id: str, year_month: str, *, ph_today: str | None = None) -> dict[str, Any]:
    """Only genuine issues; never synthesize a month by replaying today's model."""
    from calendar import monthrange
    year, month = map(int, str(year_month)[:7].split("-"))
    today = str(ph_today or philippine_today())[:10]
    rows = []
    for number in range(1, monthrange(year, month)[1] + 1):
        day = f"{year:04d}-{month:02d}-{number:02d}"
        issue = forecast_for_cell(cell_id=cell_id, issue_date_ph=day, ph_today=today)
        rows.append({**issue, "date": day})
    return {"cell_id": cell_id, "year_month": str(year_month)[:7], "ph_today": today,
            "public_label": PUBLIC_LABEL, "study": STUDY, "days": rows,
            "percentage_supported": not forecast_unavailable_reason(),
            "note": "Only approved, matching, timely archived issues are shown; missing issues are gaps. No historical reconstruction is published as a forecast."}


def _overlay_cell(cell_id: str) -> dict[str, Any]:
    """A square's grid position, centre and bounds. Cached: the grid never moves;
    callers copy the dict and never change it."""

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


def _ring_touches_study(ring: list[list[float]]) -> bool:
    """Whether a boundary reaches the Mindanao study grid, probed at its corners and centre."""

    lons = [float(lon) for lon, _ in ring]
    lats = [float(lat) for _, lat in ring]
    probe_lons = lons + [sum(lons) / len(lons)]
    probe_lats = lats + [sum(lats) / len(lats)]
    xs, ys = indices(probe_lons, probe_lats)
    study = _study_set()
    return any(cell_identifier(x, y) in study for x, y in zip(xs, ys))


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
    """Continuous 0–1 prediction surface for evaluated cells touching a boundary.

    This bulk path is read-only: it reuses preserved forecasts where available and
    scores the remaining cells without turning the selected polygon into one chance.
    Only squares inside the evaluated Maguindanao box are scored, the same rule as
    the square and month paths; other Mindanao squares stay unshaded, never 0%.
    """

    ring = normalize_ring(coordinates)
    day = str(issue_date_ph or philippine_today())[:10]
    today = str(ph_today or philippine_today())[:10]
    ring_box = polygon_bbox(ring)
    selected_cells = [
        cell
        for cell in (_overlay_cell(cell_id) for cell_id in sorted(_eval_set()))
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
        if _ring_touches_study(ring):
            return {
                **base,
                "status": "coverage_status_only",
                "reason": (
                    "Inside Mindanao, but outside the Maguindanao v2.1 evaluated box. "
                    "Percentages wait for island-wide clear-pass evaluation."
                ),
                "extent": None,
                "highest_square": None,
            }
        return {
            **base,
            "status": "unsupported",
            "reason": "Outside Mindanao — hotspot-forecast percentages are not evaluated here.",
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
        # No hand-made support record: the check derives study and evaluated-box
        # membership from the cell itself, exactly as for a single square.
        support=None,
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
    rows = []
    archive = store or HotspotForecastStore()
    archived = archive.for_day(day)
    for cell in selected_cells:
        preserved = archived.get(cell["cell_id"])
        if not _timely_selected_issue(preserved, selection or {}, day):
            continue
        probability = float(preserved["probability"])
        rows.append({**cell, "probability": probability,
                     "probability_percent": round(probability * 100),
                     "issuance_kind": "preserved_archive", "experimental": False})
    if not rows:
        return {**base, "status": "unavailable", "extent": None, "highest_square": None,
                "reason": "No timely issued forecasts from the approved model are archived here."}

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
