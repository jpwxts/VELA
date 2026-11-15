"""Durable Philippine observation store shared by the web app and refresh worker.

Stores FIRMS detections and per-feed check outcomes once per national retrieval so
Mindanao, municipality, and drawn-plot queries can reuse the same rows.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from vela.settings import WRITABLE_DATA_DIR

STORE_PATH = WRITABLE_DATA_DIR / "observations" / "philippines.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    record_id TEXT PRIMARY KEY,
    ph_date TEXT NOT NULL,
    acq_date TEXT NOT NULL,
    acq_time TEXT,
    platform TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    confidence TEXT,
    frp REAL,
    source TEXT,
    geometry_scope TEXT NOT NULL DEFAULT 'philippines',
    retrieved_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detections_ph_date ON detections(ph_date);
CREATE INDEX IF NOT EXISTS idx_detections_platform ON detections(platform);

CREATE TABLE IF NOT EXISTS feed_checks (
    check_id TEXT PRIMARY KEY,
    ph_date TEXT NOT NULL,
    platform TEXT NOT NULL,
    status TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    checked_at TEXT NOT NULL,
    UNIQUE(ph_date, platform, checked_at)
);
CREATE INDEX IF NOT EXISTS idx_feed_checks_ph_date ON feed_checks(ph_date);

CREATE TABLE IF NOT EXISTS activity_cell_days (
    cell_day_id TEXT PRIMARY KEY,
    cell_id TEXT NOT NULL,
    ph_date TEXT NOT NULL,
    activity_value REAL,
    platform TEXT,
    method TEXT,
    coverage_status TEXT,
    model_version TEXT,
    numerator REAL,
    denominator REAL,
    payload_json TEXT,
    processed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_ph_date ON activity_cell_days(ph_date);

CREATE TABLE IF NOT EXISTS checkpoints (
    name TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _connect(path: Path | None = None) -> sqlite3.Connection:
    store = Path(path) if path else STORE_PATH
    store.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(store)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def detection_record_id(platform: str, lat: float, lon: float, acq_date: str, acq_time: str | None) -> str:
    raw = f"{platform}|{acq_date}|{acq_time or ''}|{lat:.5f}|{lon:.5f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ObservationStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else STORE_PATH

    def upsert_detections(self, rows: Iterable[dict[str, Any]], *, retrieved_at: str | None = None) -> int:
        stamp = retrieved_at or datetime.now(timezone.utc).isoformat()
        written = 0
        with _connect(self.path) as connection:
            for row in rows:
                platform = str(row.get("platform") or "Unrecognized")
                lat = float(row["lat"])
                lon = float(row["lon"])
                acq_date = str(row.get("acq_date") or "")[:10]
                acq_time = row.get("acq_time") or row.get("acq_time_raw")
                ph_date = str(row.get("acq_date_ph") or row.get("ph_date") or acq_date)[:10]
                record_id = detection_record_id(platform, lat, lon, acq_date, str(acq_time or ""))
                payload = json.dumps(row, sort_keys=True, default=str)
                connection.execute(
                    """
                    INSERT INTO detections (
                        record_id, ph_date, acq_date, acq_time, platform, lat, lon,
                        confidence, frp, source, geometry_scope, retrieved_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id) DO UPDATE SET
                        ph_date = excluded.ph_date,
                        retrieved_at = excluded.retrieved_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        record_id,
                        ph_date,
                        acq_date,
                        str(acq_time or ""),
                        platform,
                        lat,
                        lon,
                        None if row.get("confidence") is None else str(row.get("confidence")),
                        None if row.get("frp") is None else float(row.get("frp")),
                        row.get("source"),
                        row.get("geometry_scope") or "philippines",
                        stamp,
                        payload,
                    ),
                )
                written += 1
            connection.commit()
        return written

    def record_feed_check(
        self,
        *,
        ph_date: str,
        platform: str,
        status: str,
        count: int = 0,
        message: str | None = None,
        checked_at: str | None = None,
    ) -> None:
        stamp = checked_at or datetime.now(timezone.utc).isoformat()
        check_id = hashlib.sha256(f"{ph_date}|{platform}|{stamp}".encode()).hexdigest()[:32]
        with _connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO feed_checks (check_id, ph_date, platform, status, count, message, checked_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (check_id, ph_date, platform, status, int(count), message, stamp),
            )
            connection.commit()

    def detections_for_ph_date(self, ph_date: str) -> list[dict]:
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload_json, retrieved_at FROM detections WHERE ph_date = ? ORDER BY acq_date, acq_time",
                (ph_date,),
            ).fetchall()
        out = []
        for row in rows:
            item = json.loads(row["payload_json"])
            item["retrieved_at"] = row["retrieved_at"]
            out.append(item)
        return out

    def heat_days_for_month(self, year: int, month: int) -> list[dict]:
        prefix = f"{year:04d}-{month:02d}"
        with _connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT ph_date AS date, COUNT(*) AS detection_count,
                       GROUP_CONCAT(DISTINCT platform) AS platforms
                FROM detections
                WHERE ph_date LIKE ?
                GROUP BY ph_date
                ORDER BY ph_date
                """,
                (f"{prefix}%",),
            ).fetchall()
        return [
            {
                "date": row["date"],
                "detection_count": int(row["detection_count"]),
                "platforms": [part for part in str(row["platforms"] or "").split(",") if part],
            }
            for row in rows
        ]

    def latest_detection_time(self) -> str | None:
        """Latest satellite acquisition time (not retrieval time)."""
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT acq_date, acq_time, payload_json FROM detections"
            ).fetchall()
        latest = None
        for row in rows:
            acq_date = row["acq_date"] or ""
            acq_time = row["acq_time"] or ""
            if not acq_date:
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                    acq_date = str(payload.get("acq_date") or "")
                    acq_time = str(payload.get("acq_time") or acq_time or "")
                except (TypeError, json.JSONDecodeError):
                    continue
            if not acq_date:
                continue
            time_part = acq_time if ":" in str(acq_time) else (
                f"{str(acq_time).zfill(4)[:2]}:{str(acq_time).zfill(4)[2:]}" if acq_time else "00:00"
            )
            stamp = f"{acq_date}T{time_part}:00+00:00" if len(time_part) <= 5 else f"{acq_date}T{time_part}+00:00"
            if latest is None or stamp > latest:
                latest = stamp
        return latest

    def latest_successful_check(self, platform: str | None = None) -> dict | None:
        with _connect(self.path) as connection:
            if platform:
                row = connection.execute(
                    """
                    SELECT ph_date, platform, status, count, checked_at, message
                    FROM feed_checks
                    WHERE status IN ('ok', 'ok_zero') AND platform = ?
                    ORDER BY checked_at DESC
                    LIMIT 1
                    """,
                    (platform,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT ph_date, platform, status, count, checked_at, message
                    FROM feed_checks
                    WHERE status IN ('ok', 'ok_zero')
                    ORDER BY checked_at DESC
                    LIMIT 1
                    """
                ).fetchone()
        return None if row is None else dict(row)

    def set_checkpoint(self, name: str, value: dict) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        with _connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO checkpoints (name, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (name, json.dumps(value, sort_keys=True), stamp),
            )
            connection.commit()

    def get_checkpoint(self, name: str) -> dict | None:
        with _connect(self.path) as connection:
            row = connection.execute(
                "SELECT value_json FROM checkpoints WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def upsert_activity_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        stamp = datetime.now(timezone.utc).isoformat()
        written = 0
        with _connect(self.path) as connection:
            for row in rows:
                cell_id = str(row["cell_id"])
                ph_date = str(row["ph_date"])[:10]
                cell_day_id = f"{cell_id}|{ph_date}"
                connection.execute(
                    """
                    INSERT INTO activity_cell_days (
                        cell_day_id, cell_id, ph_date, activity_value, platform, method,
                        coverage_status, model_version, numerator, denominator,
                        payload_json, processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cell_day_id) DO UPDATE SET
                        activity_value = excluded.activity_value,
                        platform = excluded.platform,
                        method = excluded.method,
                        coverage_status = excluded.coverage_status,
                        model_version = excluded.model_version,
                        numerator = excluded.numerator,
                        denominator = excluded.denominator,
                        payload_json = excluded.payload_json,
                        processed_at = excluded.processed_at
                    """,
                    (
                        cell_day_id,
                        cell_id,
                        ph_date,
                        row.get("activity_value"),
                        row.get("platform"),
                        row.get("method"),
                        row.get("coverage_status"),
                        row.get("model_version"),
                        row.get("numerator"),
                        row.get("denominator"),
                        json.dumps(row, sort_keys=True, default=str),
                        stamp,
                    ),
                )
                written += 1
            connection.commit()
        return written

    def activity_for_ph_date(self, ph_date: str) -> dict | None:
        with _connect(self.path) as connection:
            rows = connection.execute(
                "SELECT * FROM activity_cell_days WHERE ph_date = ?",
                (ph_date,),
            ).fetchall()
        if not rows:
            return None
        values = [row["activity_value"] for row in rows if row["activity_value"] is not None]
        if not values:
            return {
                "ph_date": ph_date,
                "activity_rate": None,
                "activity_denominator": 0,
                "numerator": 0.0,
                "cell_days": len(rows),
            }
        numerator = float(sum(values))
        denominator = len(values)
        return {
            "ph_date": ph_date,
            "activity_rate": numerator / denominator,
            "activity_denominator": denominator,
            "numerator": numerator,
            "cell_days": len(rows),
            "processed_at": max(row["processed_at"] for row in rows),
        }


def philippine_today(now: datetime | None = None) -> date:
    from zoneinfo import ZoneInfo

    stamp = now or datetime.now(timezone.utc)
    return stamp.astimezone(ZoneInfo("Asia/Manila")).date()
