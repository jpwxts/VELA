"""Year split and the reserved-region rule."""

from __future__ import annotations

from vela.settings import settings


def split_for_year(year: int, config: dict | None = None) -> str:
    cfg = config or settings()
    value = int(year)
    train_start, train_end = cfg["train_years"]
    tune_start, tune_end = cfg["tune_years"]
    test_start, test_end = cfg["test_years"]
    if train_start <= value <= train_end:
        return "train"
    if tune_start <= value <= tune_end:
        return "tune"
    if test_start <= value <= test_end:
        return "test"
    return "outside"


def is_development_role(role: str) -> bool:
    return role != "transfer"
