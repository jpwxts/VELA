"""Durable store for issued Philippine onset forecasts and later outcomes.

Issued forecasts are write-once for (scope, cell_id, issue_date_ph). Live satellite
updates after midnight must not rewrite the probability that was issued at 00:00.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vela.settings import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS onset_issues (
    issue_key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    issue_date_ph TEXT NOT NULL,
    issued_at_utc TEXT NOT NULL,
    model_version TEXT,
    feature_schema_version TEXT,
    historical_simulation INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_onset_issues_day ON onset_issues(scope, issue_date_ph);
CREATE TABLE IF NOT EXISTS onset_outcomes (
    outcome_key TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    issue_date_ph TEXT NOT NULL,
    status TEXT NOT NULL,
    label TEXT NOT NULL,
    source TEXT,
    recorded_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _issue_key(scope: str, cell_id: str, issue_date_ph: str) -> str:
    return f"{scope}|{cell_id}|{issue_date_ph}"


class OnsetForecastStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (DATA_DIR / "observations" / "philippines_onset.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def put_if_absent(self, payload: dict[str, Any]) -> dict[str, Any]:
        scope = str(payload["scope"])
        cell_id = str(payload["cell_id"])
        issue_date_ph = str(payload["issue_date_ph"])[:10]
        existing = self.get(cell_id=cell_id, issue_date_ph=issue_date_ph, scope=scope)
        if existing is not None:
            return existing
        issued_at = payload.get("issued_at_utc") or datetime.now(timezone.utc).isoformat()
        stored = dict(payload)
        stored["issued_at_utc"] = issued_at
        stored["historical_simulation"] = bool(payload.get("historical_simulation"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO onset_issues (
                    issue_key, scope, cell_id, issue_date_ph, issued_at_utc,
                    model_version, feature_schema_version, historical_simulation, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _issue_key(scope, cell_id, issue_date_ph),
                    scope,
                    cell_id,
                    issue_date_ph,
                    issued_at,
                    payload.get("model_version"),
                    payload.get("feature_schema_version"),
                    1 if stored["historical_simulation"] else 0,
                    json.dumps(stored),
                ),
            )
            connection.commit()
        return self.get(cell_id=cell_id, issue_date_ph=issue_date_ph, scope=scope) or stored

    def get(self, *, cell_id: str, issue_date_ph: str, scope: str = "mindanao") -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM onset_issues WHERE issue_key = ?",
                (_issue_key(scope, cell_id, str(issue_date_ph)[:10]),),
            ).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    def record_outcome(
        self,
        *,
        cell_id: str,
        issue_date_ph: str,
        status: str,
        label: str,
        scope: str = "mindanao",
        source: str | None = None,
        extra: dict | None = None,
    ) -> dict:
        """status: verified_wildfire | no_event_adequate_coverage | unknown"""

        recorded_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "status": status,
            "label": label,
            "source": source,
            "recorded_at_utc": recorded_at,
            **(extra or {}),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO onset_outcomes (
                    outcome_key, scope, cell_id, issue_date_ph, status, label,
                    source, recorded_at_utc, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _issue_key(scope, cell_id, str(issue_date_ph)[:10]),
                    scope,
                    cell_id,
                    str(issue_date_ph)[:10],
                    status,
                    label,
                    source,
                    recorded_at,
                    json.dumps(payload),
                ),
            )
            connection.commit()
        return payload

    def outcome_for(self, *, cell_id: str, issue_date_ph: str, scope: str = "mindanao") -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM onset_outcomes WHERE outcome_key = ?",
                (_issue_key(scope, cell_id, str(issue_date_ph)[:10]),),
            ).fetchone()
        return None if row is None else json.loads(row["payload_json"])
