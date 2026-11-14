"""Durable Philippine observation store keeps Live and History in sync."""

from __future__ import annotations

from vela.observation_store import ObservationStore, philippine_today
from vela.ph_live import live_clock, seed_public_snapshot


def test_seed_snapshot_splits_philippine_dates(tmp_path):
    store = ObservationStore(tmp_path / "ph.sqlite")
    result = seed_public_snapshot(store)
    assert result["written"] == 47
    heat = {row["date"]: row["detection_count"] for row in store.heat_days_for_month(2026, 11)}
    assert heat.get("2026-11-07") == 43
    assert heat.get("2026-11-08") == 4


def test_live_clock_uses_manila():
    clock = live_clock()
    assert clock["timezone"] == "Asia/Manila"
    assert clock["ph_today"] == philippine_today().isoformat()
