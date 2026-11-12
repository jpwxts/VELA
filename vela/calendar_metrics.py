"""Weekly activity as a share of usable cell-days."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from vela.coverage import COVERAGE_RULE

CALENDAR_METRIC = (
    "Vela divides the area into grid squares. Each square on one day counts once. "
    "The weekly percentage estimates how often those squares showed burning activity "
    "on the days with usable estimates."
)

CALENDAR_METRIC_NOTE = (
    "A square observed on Monday and Tuesday counts twice, once for each day. "
    "The value measures activity frequency; burned area and the number of separate fires "
    "are different measurements."
)


def summarize_week(eligible_rows: list[dict], config: dict) -> dict:
    """Summarize processed cell-days. An empty list is insufficient, not a clear zero."""

    minimum_count = int(config["min_usable_cell_days_per_week"])
    minimum_coverage = float(config["min_shared_coverage"])
    count = len(eligible_rows)
    if count == 0:
        return {
            "usable_cell_days": 0,
            "days_observed": 0,
            "mean_shared_coverage": None,
            "coverage_status": "insufficient",
            "clear_zero": False,
            "viirs_rate": None,
            "observed_rate": None,
            "viirs_active_cell_days": 0,
            "modis_active_cell_days": 0,
        }
    viirs_active = sum(1 for row in eligible_rows if int(row["viirs_hotspot_pixel_count"]) > 0)
    modis_active = sum(1 for row in eligible_rows if bool(row["modis_detected"]))
    shared = sum(float(row["shared_coverage_fraction"]) for row in eligible_rows) / count
    days = len({str(row["local_date"])[:10] for row in eligible_rows})
    sufficient = count >= minimum_count and shared + 1e-12 >= minimum_coverage
    viirs_rate = viirs_active / count
    observed_rate = modis_active / count
    clear_zero = sufficient and viirs_active == 0 and modis_active == 0
    return {
        "usable_cell_days": count,
        "days_observed": days,
        "mean_shared_coverage": shared,
        "coverage_status": "ok" if sufficient else "insufficient",
        "clear_zero": clear_zero,
        "viirs_rate": viirs_rate if sufficient else None,
        "observed_rate": observed_rate if sufficient else None,
        "provisional_viirs_rate": viirs_rate,
        "provisional_observed_rate": observed_rate,
        "viirs_active_cell_days": viirs_active,
        "modis_active_cell_days": modis_active,
    }


def insufficient_reason(summary: dict, config: dict) -> str | None:
    """Why a week stays unscored. A covered week with no detections has no reason."""

    if summary.get("coverage_status") == "ok":
        return None
    minimum_count = int(config["min_usable_cell_days_per_week"])
    minimum_coverage = float(config["min_shared_coverage"])
    count = int(summary.get("usable_cell_days") or 0)
    shared = summary.get("mean_shared_coverage")
    reasons = []
    if count == 0:
        reasons.append("No eligible cell-days. The rate is missing.")
    elif count < minimum_count:
        reasons.append(f"Usable cell-days are {count}; at least {minimum_count} are required.")
    if count and shared is not None and shared + 1e-12 < minimum_coverage:
        reasons.append(
            f"Mean shared coverage is {shared:.3f}; at least {minimum_coverage:.1f} is required."
        )
    return " ".join(reasons) or "Coverage is insufficient."


def missing_rate_dates(eligible_days: set[str], excluded_days: set[str]) -> list[dict]:
    """Dates with only excluded cells stay visible, and their rate stays missing."""

    return [
        {"local_date": day, "coverage_status": "insufficient", "rate": None}
        for day in sorted(excluded_days - eligible_days)
    ]


def group_by_week(rows: list[dict]) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for row in rows:
        day = date.fromisoformat(str(row["local_date"])[:10])
        monday = day.fromordinal(day.toordinal() - day.weekday())
        grouped[monday.isoformat()].append(row)
    return dict(grouped)


def metric_text() -> str:
    return f"{CALENDAR_METRIC} {COVERAGE_RULE}"
