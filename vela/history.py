"""Monthly views of the same cell-day contributions used by the weekly history."""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta

from vela import serving
from vela.contributions import tally_activity
from vela.land_check import point_in_ring, polygon_bbox


HISTORY_METRIC = (
    "Burning activity is the share of observed grid squares with activity on days "
    "that have usable estimates. It is not the percentage of land burned."
)


def build_monthly_history(ring: list[list[float]], year: int, month: int, *, today: date | None = None) -> dict:
    """Keep gaps, clear zeros, insufficient coverage and held-out dates distinct.

    Daily values are published only within weeks that meet the existing coverage
    rule. Month totals weight those daily values by their cell-day denominators.
    Model evaluation observations retain the weekly history's hold-out policy.
    """

    today = today or date.today()
    box = polygon_bbox(ring)
    label = serving.region_label(*box)

    def land_frame(path):
        frame = serving._filter_box(serving._frame(path), *box)
        if not frame.empty:
            inside = [point_in_ring(float(lon), float(lat), ring)
                      for lon, lat in zip(frame["center_lon"], frame["center_lat"])]
            frame = frame.loc[inside].copy()
        return frame

    paired = land_frame(serving.PAIRED_PATH)
    excluded = land_frame(serving.EXCLUDED_PATH)
    stored_dates = sorted({str(value)[:10] for frame in (paired, excluded)
                           if not frame.empty for value in frame["local_date"]
                           if str(value)[:10] <= today.isoformat()})
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    # Include complete weeks at year boundaries before applying coverage rules.
    first = start - timedelta(days=start.weekday())
    last = end + timedelta(days=6 - end.weekday())
    eligible = serving._in_week(paired, first, min(last, today))
    left_out = serving._in_week(excluded, first, min(last, today))
    artifact = serving.load_model() if serving.model_status()["ready"] and (not eligible.empty or not left_out.empty) else None
    scene = serving._week_scene(eligible, left_out, artifact=artifact)
    by_day = defaultdict(list)
    by_week = defaultdict(list)
    for item in scene["contributions"]:
        day = date.fromisoformat(item["local_date"])
        by_day[day.isoformat()].append(item)
        monday = day - timedelta(days=day.weekday())
        by_week[monday.isoformat()].append(item)
    weeks = {stamp: tally_activity(items) for stamp, items in by_week.items()}
    processed = set(stored_dates)
    all_days = []
    day = start
    while day <= end:
        stamp = day.isoformat()
        items = by_day.get(stamp, [])
        monday = day - timedelta(days=day.weekday())
        weekly = weeks.get(monday.isoformat(), {})
        tally = tally_activity(items)
        hidden = serving._held_out((monday + timedelta(days=3)).year, label)
        if day > today:
            status = "future"
        elif stamp not in processed:
            status = "not_processed"
        elif hidden:
            status = "hidden"
        elif not weekly.get("coverage_established") or tally["activity_rate"] is None:
            status = "insufficient"
        else:
            status = tally["activity_status"]
        public = status in {"complete", "partial"}
        all_days.append({
            "date": stamp,
            "activity_rate": tally["activity_rate"] if public else None,
            "activity_status": status,
            "eligible_cell_days": tally["eligible_coverage_cell_days"],
            "estimated_cell_days": tally["activity_estimate_cell_days"] if public else 0,
            "activity_denominator": tally["activity_denominator"] if public else None,
            "clear_zero": bool(public and status == "complete" and tally["activity_rate"] == 0),
        })
        day += timedelta(days=1)

    months = []
    for number in range(1, 13):
        key = f"{year}-{number:02d}"
        days = [entry for entry in all_days if entry["date"].startswith(key)]
        published = [entry for entry in days if entry["activity_rate"] is not None]
        denominator = sum(entry["activity_denominator"] for entry in published)
        rate = (sum(entry["activity_rate"] * entry["activity_denominator"]
                    for entry in published) / denominator) if denominator else None
        status = "not_processed"
        if published:
            status = "complete" if len(published) == len(days) and all(
                entry["activity_status"] == "complete" for entry in published
            ) else "partial"
        elif all(entry["activity_status"] == "future" for entry in days):
            status = "future"
        elif any(entry["activity_status"] == "hidden" for entry in days):
            status = "hidden"
        elif any(entry["activity_status"] == "insufficient" for entry in days):
            status = "insufficient"
        months.append({
            "month": key,
            "activity_rate": rate,
            "activity_status": status,
            "days_with_estimates": len(published),
            "days_in_month": monthrange(year, number)[1],
            "activity_denominator": denominator or None,
        })
    selected = months[month - 1]
    return {
        "year": year,
        "month": month,
        "status": "ok" if selected["activity_rate"] is not None else selected["activity_status"],
        "metric": HISTORY_METRIC,
        "date_basis": "local observation date",
        "region": label,
        "summary": selected,
        "days": [entry for entry in all_days if entry["date"].startswith(f"{year}-{month:02d}")],
        "months": months,
        "available_months": sorted({stamp[:7] for stamp in stored_dates if stamp >= "1990-01-01"}),
        "first_observation": stored_dates[0] if stored_dates else None,
        "last_observation": stored_dates[-1] if stored_dates else None,
    }
