"""Store each issued forecast once so a later check can use the same lead time."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS forecast_issues (
    issue_id TEXT PRIMARY KEY,
    region_key TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefs (
    region_key TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (region_key, issue_id)
);
"""


class ForecastArchive:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, issue_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT issued_at, payload FROM forecast_issues WHERE issue_id = ?",
                (issue_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        payload["issued_at"] = row["issued_at"]
        return payload

    def put_if_absent(self, issue_id: str, region_key: str, payload: dict) -> dict:
        existing = self.get(issue_id)
        if existing is not None:
            return existing
        issued_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        stored = dict(payload)
        stored["issued_at"] = issued_at
        stored["verification_status"] = "pending"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO forecast_issues (issue_id, region_key, issued_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (issue_id, region_key, issued_at, json.dumps(stored)),
            )
        return self.get(issue_id) or stored

    def brief_already_sent(self, region_key: str, issue_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM briefs WHERE region_key = ? AND issue_id = ?",
                (region_key, issue_id),
            ).fetchone()
        return row is not None

    def mark_brief_sent(self, region_key: str, issue_id: str) -> None:
        sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO briefs (region_key, issue_id, sent_at) VALUES (?, ?, ?)",
                (region_key, issue_id, sent_at),
            )
