"""Load the project configuration shipped in config/."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def writable_data_dir() -> Path:
    configured = os.environ.get("VELA_WRITABLE_DATA_DIR")
    if configured:
        return Path(configured)
    if os.environ.get("VERCEL"):
        return Path("/tmp/vela")
    return DATA_DIR


WRITABLE_DATA_DIR = writable_data_dir()


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
