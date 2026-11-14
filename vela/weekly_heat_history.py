"""Weekly heat history for a selected plot (Philippine local days).

Builds a Monday–Sunday Asia/Manila week from real FIRMS records clipped to the
selected geometry. Unchecked days stay unchecked. Failed requests never become
zeros. A one-day snapshot never implies the other six days were searched.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vela.alert_passes import distinct_passes
from vela.boundaries import geometry_bbox, geometry_from_preset, load_preset, point_in_geometry
from vela.land_check import classify_detections
from vela.public_hotspots import build_public_land_check, geojson_path
from vela.serving import build_calendar

MANILA = ZoneInfo("Asia/Manila")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_days(week_start: date) -> list[date]:
    return [week_start + timedelta(days=offset) for offset in range(7)]


def parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def format_week_range(week_start: date) -> str:
    week_end = week_start + timedelta(days=6)
    if week_start.month == week_end.month:
        return f"{week_start.day}–{week_end.day} {week_end.strftime('%B %Y')}"
    if week_start.year == week_end.year:
        return (
            f"{week_start.day} {week_start.strftime('%B')} – "
            f"{week_end.day} {week_end.strftime('%B %Y')}"
        )
    return (
        f"{week_start.day} {week_start.strftime('%B %Y')} – "
        f"{week_end.day} {week_end.strftime('%B %Y')}"
    )


def utc_dates_for_ph_day(ph_day: date) -> list[str]:
    """UTC acquisition dates that can fall on a Philippine calendar day (UTC+8)."""

    # Manila day D runs from UTC (D-1) 16:00 through UTC D 15:59.
    previous = (ph_day - timedelta(days=1)).isoformat()
    current = ph_day.isoformat()
    return [previous, current]


def ph_day_for_utc(acq_date: str, acq_time: str | None) -> str | None:
    text = str(acq_time or "00:00").strip()
    if ":" in text:
        hour, minute = [int(part) for part in text.split(":", 1)[:2]]
    else:
        digits = "".join(ch for ch in text if ch.isdigit()).zfill(4)[-4:]
        hour, minute = int(digits[:2]), int(digits[2:])
    try:
        stamp = datetime(
            int(acq_date[:4]),
            int(acq_date[5:7]),
            int(acq_date[8:10]),
            hour,
            minute,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return stamp.astimezone(MANILA).date().isoformat()


def _detection_rows(hotspot_payload: dict, geometry: dict) -> list[dict]:
    # Prefer multipolygon geometry so island-group presets exclude out-of-group points.
    if isinstance(geometry, dict) and geometry.get("type"):
        heat = classify_detections(hotspot_payload, geometry=geometry)
    else:
        from vela.boundaries import primary_ring_for_display

        heat = classify_detections(hotspot_payload, primary_ring_for_display(geometry))
    rows = []
    for spot in heat.get("inside") or []:
        item = dict(spot)
        item["ph_date"] = ph_day_for_utc(str(item.get("acq_date") or ""), item.get("acq_time"))
        rows.append(item)
    return rows


def _summarize_day(
    *,
    ph_day: date,
    status: str,
    detections: list[dict] | None = None,
    feeds: list[dict] | None = None,
    source: str | None = None,
    message: str | None = None,
    checked: bool | None = None,
) -> dict:
    detections = list(detections or [])
    passes = distinct_passes(detections, observation_date=ph_day.isoformat())
    platforms = sorted({row.get("platform") for row in detections if row.get("platform")})
    plain = {
        "heat_detected": "Heat detected",
        "no_readings": "Checked · no readings returned",
        "partial": "Partial source availability",
        "not_checked": "Not checked",
        "request_failed": "Request failed · not counted as zero",
        "snapshot_only": "Available from saved snapshot",
    }.get(status, status)
    if checked is None:
        checked = status in {"heat_detected", "no_readings", "partial", "snapshot_only"}
    return {
        "date": ph_day.isoformat(),
        "label": ph_day.strftime("%a %-d" if False else "%a %d").replace(" 0", " "),
        "weekday": ph_day.strftime("%A"),
        "status": status,
        "plain_status": plain,
        "detection_count": len(detections),
        "pass_count": len(passes),
        "platforms": platforms,
        "passes": [
            {
                "platform": row["platform"],
                "time_utc": row["acq_time"],
                "time_local": row.get("time_local") or row.get("acq_time_ph"),
                "acq_date_ph": row.get("acq_date_ph"),
                "detection_count": row.get("detection_count"),
            }
            for row in passes
        ],
        "feeds": feeds or [],
        "source": source,
        "message": message,
        "checked": checked,
        "has_heat": status in {"heat_detected", "snapshot_only"} and len(detections) > 0,
    }


def _lead_sentence(days: list[dict]) -> dict:
    checked = [day for day in days if day["checked"]]
    heat_days = [day for day in days if day["checked"] and day["has_heat"]]
    unchecked = [day for day in days if not day["checked"] and day["status"] != "request_failed"]
    failed = [day for day in days if day["status"] == "request_failed"]
    partial = [day for day in days if day["status"] == "partial"]

    if len(checked) == 1 and len(unchecked) == 6:
        only = checked[0]
        day = parse_day(only["date"])
        lead = f"Available readings cover {day.day} {day.strftime('%B')}."
        action = "check_rest"
    elif not checked:
        lead = "No days in this week have been checked for satellite heat yet."
        action = "check_week"
    else:
        lead = (
            f"Satellites detected heat on {len(heat_days)} of the {len(checked)} "
            f"day{'s' if len(checked) != 1 else ''} checked."
        )
        action = "check_rest" if unchecked else None

    notes = []
    if unchecked:
        notes.append(
            f"{len(unchecked)} day{'s' if len(unchecked) != 1 else ''} not checked yet."
        )
    if partial:
        notes.append(
            f"{len(partial)} day{'s' if len(partial) != 1 else ''} only partially available."
        )
    if failed:
        notes.append(
            f"{len(failed)} request{'s' if len(failed) != 1 else ''} failed and "
            "were not treated as zero detections."
        )
    return {
        "lead": lead,
        "notes": notes,
        "action": action,
        "checked_count": len(checked),
        "heat_day_count": len(heat_days),
        "unchecked_count": len(unchecked),
        "failed_count": len(failed),
        "partial_count": len(partial),
    }


def _weekly_estimate(geometry: dict, week_start: date, label: str) -> dict:
    west, south, east, north = geometry_bbox(geometry)
    calendar = build_calendar(west, south, east, north, week_start.year)
    match = None
    for week in calendar.get("weeks") or []:
        start = parse_day(week["week_start"])
        end = parse_day(week["week_end"])
        if start <= week_start <= end or start == week_start:
            match = week
            break
    if match is None:
        return {
            "status": "unavailable",
            "rate": None,
            "denominator": None,
            "plain": (
                "The coverage-adjusted weekly estimate is unavailable for this selection "
                "and week. Observed heat history above still stands."
            ),
            "reason": calendar.get("status") or "no_matching_week",
            "region": label,
        }
    status = match.get("activity_status") or "unavailable"
    rate = match.get("activity_rate")
    denom = match.get("activity_denominator")
    if status == "complete" and rate is not None:
        plain = (
            f"Among {denom} usable cell-days this week, about {round(float(rate) * 100)}% "
            "showed burning activity in the coverage-adjusted estimate."
        )
    elif status == "partial" and rate is not None:
        plain = (
            f"Partial estimate: about {round(float(rate) * 100)}% of the "
            f"{denom} cell-days with usable estimates showed burning activity. "
            "Some days in the week lack estimates."
        )
    else:
        plain = (
            "No published coverage-adjusted weekly estimate for this week. "
            "Observed heat detections above remain visible and are not replaced by a hotspot-day percentage."
        )
    return {
        "status": status,
        "rate": None if rate is None else float(rate),
        "percentage": None if rate is None else round(float(rate) * 100),
        "denominator": denom,
        "plain": plain,
        "week_start": match.get("week_start"),
        "week_end": match.get("week_end"),
        "region": label,
        "note": (
            "This percentage is the existing weekly activity estimate. "
            "It is not the share of calendar days that returned hotspots."
        ),
    }


def _clip_rows_to_geometry(rows: list[dict], geometry: dict) -> list[dict]:
    clipped = []
    for row in rows:
        try:
            lon = float(row.get("lon"))
            lat = float(row.get("lat"))
        except (TypeError, ValueError):
            continue
        if point_in_geometry(lon, lat, geometry):
            clipped.append(row)
    return clipped


def _snapshot_day_payload(day: str, region: str, geometry: dict | None = None) -> dict | None:
    path = geojson_path(day)
    if not path.is_file():
        return None
    # Use national snapshot as the feature pool; clip to Mindanao preset or custom plot.
    base_region = "philippines" if region in {"philippines", "custom", "mindanao"} else "philippines"
    payload = build_public_land_check(day=day, region=base_region)
    if region == "mindanao" and geometry is None:
        geometry = geometry_from_preset("mindanao")
    if geometry is not None and "type" in geometry:
        heat = payload.get("heat") or {}
        inside = _clip_rows_to_geometry(list(heat.get("inside") or []), geometry)
        nearby = _clip_rows_to_geometry(list(heat.get("nearby") or []), geometry)
        payload = {
            **payload,
            "heat": {**heat, "inside": inside, "nearby": nearby, "count_inside": len(inside)},
        }
    return payload


def build_weekly_heat_history(
    *,
    anchor_date: str,
    geometry: dict | None = None,
    preset_id: str | None = None,
    label: str | None = None,
    known_days: list[str] | None = None,
    fetch_missing: bool = False,
    firms_client=None,
    platforms: list[str] | None = None,
    timezone_name: str = "Asia/Manila",
) -> dict:
    """Assemble one Asia/Manila week of heat history for the selected geometry."""

    if timezone_name != "Asia/Manila":
        raise ValueError("Weekly heat history currently supports Asia/Manila only.")
    if preset_id:
        preset = load_preset(preset_id)
        geometry = preset["geometry"]
        label = label or preset.get("name") or preset_id
        region_key = preset_id
    else:
        if not geometry:
            raise ValueError("geometry or preset_id is required.")
        label = label or "Selected plot"
        region_key = "custom"

    anchor = parse_day(anchor_date)
    # Treat the map's selected calendar date as the Philippine day of interest.
    week_start = monday_of(anchor)
    days = week_days(week_start)
    known = {str(day)[:10] for day in (known_days or [])}
    # Public snapshot days that exist on disk are known without implying a full week search.
    for day in days:
        if geojson_path(day.isoformat()).is_file():
            known.add(day.isoformat())

    # Load UTC-day snapshots once; assign detections by Philippine local date.
    # A single saved UTC day never marks the other six PH days as fully checked.
    # Custom plots still reuse the national snapshot, clipped to their polygon.
    snapshot_by_ph: dict[str, list[dict]] = {}
    snapshot_feeds_by_utc: dict[str, list[dict]] = {}
    searched_ph_from_snapshot: set[str] = set()
    candidate_utc = sorted(known | {d.isoformat() for d in days})
    for utc_day in candidate_utc:
        if not geojson_path(utc_day).is_file():
            continue
        snapshot = _snapshot_day_payload(utc_day, region_key, geometry)
        if not snapshot:
            continue
        heat = snapshot.get("heat") or {}
        snapshot_feeds_by_utc[utc_day] = list(heat.get("feeds") or [])
        # The UTC snapshot day itself is the only PH day we treat as searched.
        searched_ph_from_snapshot.add(utc_day)
        for row in heat.get("inside") or []:
            ph = (
                str(row.get("acq_date_ph") or "")[:10]
                or ph_day_for_utc(str(row.get("acq_date") or utc_day), row.get("acq_time"))
            )
            if not ph:
                continue
            snapshot_by_ph.setdefault(ph, []).append(row)

    day_rows: list[dict] = []
    for ph_day in days:
        iso = ph_day.isoformat()
        if iso in snapshot_by_ph or iso in searched_ph_from_snapshot:
            detections = list(snapshot_by_ph.get(iso) or [])
            feeds = snapshot_feeds_by_utc.get(iso) or next(
                iter(snapshot_feeds_by_utc.values()), []
            )
            searched = iso in searched_ph_from_snapshot
            if detections and searched:
                day_rows.append(
                    _summarize_day(
                        ph_day=ph_day,
                        status="heat_detected",
                        detections=detections,
                        feeds=feeds,
                        source="public_snapshot",
                        message="From the saved FIRMS snapshot for this Philippine day.",
                        checked=True,
                    )
                )
            elif detections and not searched:
                # Spill onto an adjacent PH day without claiming that day was searched.
                day_rows.append(
                    _summarize_day(
                        ph_day=ph_day,
                        status="heat_detected",
                        detections=detections,
                        feeds=feeds,
                        source="public_snapshot",
                        message=(
                            "Readings whose UTC acquisition falls on the previous calendar day "
                            "land on this Philippine date."
                        ),
                        checked=False,
                    )
                )
            elif searched:
                day_rows.append(
                    _summarize_day(
                        ph_day=ph_day,
                        status="no_readings",
                        detections=[],
                        feeds=feeds,
                        source="public_snapshot",
                        message="Snapshot checked for this day; no readings inside the boundary.",
                        checked=True,
                    )
                )
            continue

        # Snapshots never imply a full week. Live/cache pulls run only for:
        # - days the session already checked (known_days), or
        # - an explicit "check the rest of this week" request (fetch_missing).
        should_fetch = bool(firms_client) and (fetch_missing or iso in known)
        if not should_fetch:
            day_rows.append(
                _summarize_day(
                    ph_day=ph_day,
                    status="not_checked",
                    message="This day has not been searched yet.",
                )
            )
            continue

        # Live/cache fetch: query overlapping UTC dates, clip to polygon, assign by PH day.
        west, south, east, north = geometry_bbox(geometry)
        pad = 0.05
        detections: list[dict] = []
        feeds: list[dict] = []
        failed = False
        partial = False
        for utc_day in utc_dates_for_ph_day(ph_day):
            try:
                payload = firms_client.hotspots(
                    west - pad,
                    south - pad,
                    east + pad,
                    north + pad,
                    utc_day,
                    platforms or ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"],
                )
            except Exception:  # noqa: BLE001
                failed = True
                continue
            for result in payload.get("results") or []:
                feeds.append(
                    {
                        "platform": result.get("platform"),
                        "status": result.get("status"),
                        "coverage": result.get("coverage"),
                        "count": result.get("count"),
                        "utc_day": utc_day,
                    }
                )
                if result.get("status") in {"request_failed", "not_configured"}:
                    failed = True
                if result.get("coverage") in {"partial", "unknown"} and result.get("status") == "ok":
                    partial = True
            for row in _detection_rows(payload, geometry):
                if row.get("ph_date") == iso:
                    detections.append(row)

        if failed and not detections:
            day_rows.append(
                _summarize_day(
                    ph_day=ph_day,
                    status="request_failed",
                    detections=[],
                    feeds=feeds,
                    source="firms",
                    message="The satellite request failed. This day is not recorded as zero detections.",
                )
            )
        elif detections:
            day_rows.append(
                _summarize_day(
                    ph_day=ph_day,
                    status="partial" if partial else "heat_detected",
                    detections=detections,
                    feeds=feeds,
                    source="firms",
                )
            )
        elif partial:
            day_rows.append(
                _summarize_day(
                    ph_day=ph_day,
                    status="partial",
                    detections=[],
                    feeds=feeds,
                    source="firms",
                    message="Some satellite sources were unavailable; absence of heat is not proven.",
                )
            )
        else:
            day_rows.append(
                _summarize_day(
                    ph_day=ph_day,
                    status="no_readings",
                    detections=[],
                    feeds=feeds,
                    source="firms",
                    message="Completed search returned no readings inside the boundary.",
                )
            )

    summary = _lead_sentence(day_rows)
    estimate = _weekly_estimate(geometry, week_start, label)
    return {
        "ok": True,
        "title": "Weekly heat history",
        "place_name": label,
        "timezone": "Asia/Manila",
        "anchor_date": anchor.isoformat(),
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "week_range_label": format_week_range(week_start),
        "previous_week_start": (week_start - timedelta(days=7)).isoformat(),
        "next_week_start": (week_start + timedelta(days=7)).isoformat(),
        "days": day_rows,
        "summary": summary,
        "weekly_estimate": estimate,
        "geometry": geometry,
        "region_id": region_key,
        "rules": {
            "clip": "FIRMS bounding-box pulls are clipped to the selected polygon or multipolygon before counts.",
            "timezone": "Day buttons use Asia/Manila. UTC acquisitions are assigned by local datetime.",
            "snapshot": "A saved one-day snapshot never marks the other six days as checked.",
            "failures": "A failed request never creates a zero-detection day.",
            "passes": "Repeat passes are counted separately from adjacent pixels in one pass.",
            "percentage": (
                "The coverage-adjusted weekly percentage below is the existing weekly API estimate, "
                "not the share of days with returned hotspots."
            ),
        },
    }
