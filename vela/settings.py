"""Load the project configuration shipped in config/."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def _load(name: str) -> dict:
    with (CONFIG_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def settings() -> dict:
    return _load("settings.json")


@lru_cache(maxsize=1)
def regions() -> list[dict]:
    return list(_load("regions.json")["regions"])


def region_by_id(region_id: str) -> dict:
    for region in regions():
        if region["id"] == region_id:
            return region
    raise KeyError(f"Unknown region '{region_id}'. Edit config/regions.json to add it.")


def data_dir(*parts: str) -> Path:
    path = DATA_DIR.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
