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


def _display_for_day(entry: dict) -> dict:
    """Plain-language chart/calendar state from estimate + FIRMS heat overlays."""

    heat_status = entry.get("heat_status") or "not_checked"
    heat_count = int(entry.get("heat_count") or 0)
    status = entry.get("activity_status")
    rate = entry.get("activity_rate")
    has_estimate = isinstance(rate, (int, float))

    if has_estimate:
        kind = "estimate"
        if status == "partial":
            label = "Estimated burning activity · partial"
        else:
            label = "Estimated burning activity"
        detail = None
    elif heat_status == "readings" and heat_count > 0:
        kind = "heat"
        label = "Satellite heat readings"
        if status == "not_processed":
            detail = "Heat readings available · activity estimate not processed"
        elif status == "insufficient":
            detail = "Heat readings available · insufficient usable coverage for an estimate"
        else:
            detail = "Heat readings available · activity estimate unavailable"
    elif heat_status == "checked_empty":
        kind = "checked_empty"
        label = "Checked · no heat readings returned"
        detail = None if status != "not_processed" else (
            "No heat readings returned · activity estimate not processed"
        )
    elif status == "future":
        kind = "future"
        label = "Not yet observed"
        detail = None
    else:
        kind = "not_checked"
        label = "Not checked"
        detail = None

    return {
        **entry,
        "display_kind": kind,
        "display_label": label,
        "display_detail": detail,
    }


def attach_heat_overlay(
    payload: dict,
    *,
    heat_days: list[dict] | None = None,
    checked_days: list[str] | None = None,
) -> dict:
    """Merge FIRMS/session heat into monthly history without inventing estimates."""

    heat_map = {
        str(row.get("date") or "")[:10]: row
        for row in (heat_days or [])
        if row.get("date")
    }
    checked = {str(day)[:10] for day in (checked_days or [])}
    days = []
    for entry in payload.get("days") or []:
        day = dict(entry)
        iso = day["date"]
        heat = heat_map.get(iso) or {}
        count = int(heat.get("count") or heat.get("detection_count") or 0)
        queried = bool(heat.get("queried") or iso in checked or iso in heat_map)
        day["heat_area_count"] = heat.get("area_count")
        day["heat_coverage"] = heat.get("coverage") or "unknown"
        if day.get("activity_status") == "future":
            day["heat_status"] = "not_checked"
            day["heat_count"] = 0
        elif count > 0:
            day["heat_status"] = "readings"
            day["heat_count"] = count
            day["heat_source"] = heat.get("source")
        elif queried:
            day["heat_status"] = "checked_empty"
            day["heat_count"] = 0
            day["heat_source"] = heat.get("source")
        else:
            day["heat_status"] = "not_checked"
            day["heat_count"] = 0
        days.append(_display_for_day(day))
    return {**payload, "days": days}


def _fill_mindanao_store_activity(days, ring, geometry=None):
    """Use only eligible Aqua/calibrated Suomi rows; fill before all period totals."""
    from vela.activity_store import fill_history
    return fill_history(days, ring, geometry)


def build_monthly_history(ring: list[list[float]], year: int, month: int, *, today: date | None = None, geometry: dict | None = None) -> dict:
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
            from vela.boundaries import point_in_geometry
            inside = [(point_in_geometry(float(lon), float(lat), geometry) if geometry else point_in_ring(float(lon), float(lat), ring))
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
            "method_counts": tally["method_counts"],
            "clear_zero": bool(public and status == "complete" and tally["activity_rate"] == 0),
        })
        day += timedelta(days=1)

    from vela.activity_store import aggregate_days
    data_version = _fill_mindanao_store_activity(all_days, ring, geometry)
    stored_dates = sorted(set(stored_dates) | {entry["date"] for entry in all_days if entry.get("activity_rate") is not None})
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
            **aggregate_days(days),
            "month": key,
            "activity_rate": rate,
            "activity_status": status,
            "days_with_estimates": len(published),
            "days_in_month": monthrange(year, number)[1],
            "activity_denominator": denominator or None,
        })
    selected = months[month - 1]
    month_days = [entry for entry in all_days if entry["date"].startswith(f"{year}-{month:02d}")]
    grouped_weeks = defaultdict(list)
    for entry in all_days:
        stamp = date.fromisoformat(entry['date'])
        monday = stamp - timedelta(days=stamp.weekday())
        grouped_weeks[monday.isoformat()].append(entry)
    weekly_periods = [{**aggregate_days(entries), 'week_start': monday,
                       'week_end': (date.fromisoformat(monday)+timedelta(days=6)).isoformat(),
                       'period_start': entries[0]['date'], 'period_end': entries[-1]['date']}
                      for monday, entries in sorted(grouped_weeks.items())]
    return {
        "data_version": data_version,
        "weeks": weekly_periods,
        "processed_dates": stored_dates,
        "year": year,
        "month": month,
        "status": "ok" if selected["activity_rate"] is not None else selected["activity_status"],
        "metric": HISTORY_METRIC,
        "date_basis": "local observation date",
        "region": label,
        "summary": selected,
        "days": month_days,
        "months": months,
        "available_months": sorted({stamp[:7] for stamp in stored_dates if stamp >= "1990-01-01"}),
        "first_observation": stored_dates[0] if stored_dates else None,
        "last_observation": stored_dates[-1] if stored_dates else None,
    }
