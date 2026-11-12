"""Small SQLite cache. The FIRMS map key is never stored."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS response_cache (
    cache_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    stored_at TEXT NOT NULL
);
"""


class ResponseCache:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, cache_key: str, max_age_hours: float | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, stored_at FROM response_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        if max_age_hours is not None:
            stored = datetime.fromisoformat(row["stored_at"])
            if stored < datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
                return None
        return row["payload"]

    def put(self, cache_key: str, kind: str, payload: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO response_cache (cache_key, kind, payload, stored_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    kind = excluded.kind,
                    payload = excluded.payload,
                    stored_at = excluded.stored_at
                """,
                (cache_key, kind, payload, stamp),
            )
