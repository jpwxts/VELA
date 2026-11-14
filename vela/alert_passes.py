"""Distinct satellite passes and wildfire-confirmation evidence for heat alerts.

A pass is one spacecraft observation time. Neighboring pixels from the same
platform and acquisition time count as one pass, not a repeat observation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")

# Documented matching rules for future independent labels (not applied yet).
MATCH_RULES = {
    "spatial": "Alert cell (5 km) intersects verified incident footprint, or incident point falls inside the cell.",
    "temporal": "Incident date within ±1 calendar day of the UTC observation day (Asia/Manila when both are Philippine).",
    "outcomes": "Independently verified wildfire vs non-wildfire labels from agency or field sources.",
    "unmatched": "Alerts without a verified outcome remain unknown and are not scored as yes/no.",
}

MISSING_CONFIRMATION_DATASET = (
    "Independently verified Philippine wildfire and non-wildfire outcome labels "
    "matched to FIRMS heat alerts (with location, date, and wildfire / not-wildfire class). "
    "No such table exists under data/, config/, or docs/ in this repository yet."
)


def _normalize_hhmm(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if ":" in text:
        hour_text, minute_text = text.split(":", 1)
        try:
            return f"{int(hour_text):02d}:{int(minute_text[:2]):02d}"
        except ValueError:
            return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    digits = digits.zfill(4)[-4:]
    return f"{digits[:2]}:{digits[2:]}"


def _pass_key(member: dict) -> tuple[str, str, str] | None:
    platform = str(member.get("name") or member.get("platform") or "").strip()
    day = str(member.get("acq_date") or member.get("date") or member.get("observation_date") or "")[:10]
    time_text = _normalize_hhmm(
        member.get("acq_time")
        or member.get("time_utc")
        or member.get("acq_time_raw")
        or member.get("time")
    )
    if not platform or not day or not time_text:
        return None
    return platform, day, time_text


def _utc_datetime(day: str, hhmm: str) -> datetime | None:
    try:
        hour, minute = [int(part) for part in hhmm.split(":", 1)]
        return datetime(
            int(day[:4]),
            int(day[5:7]),
            int(day[8:10]),
            hour,
            minute,
            tzinfo=timezone.utc,
        )
    except (TypeError, ValueError):
        return None


def _ph_local(stamp: datetime) -> tuple[str, str]:
    local = stamp.astimezone(MANILA)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def distinct_passes(members: list[dict] | None, *, observation_date: str | None = None) -> list[dict]:
    """Collapse pixel detections into distinct (platform, UTC date, UTC time) passes."""

    grouped: dict[tuple[str, str, str], dict] = {}
    for member in members or []:
        item = dict(member)
        if not item.get("acq_date") and observation_date:
            item["acq_date"] = observation_date
        if not item.get("platform") and item.get("name"):
            item["platform"] = item["name"]
        key = _pass_key(item)
        if key is None:
            continue
        platform, day, hhmm = key
        if key not in grouped:
            stamp = _utc_datetime(day, hhmm)
            local_date, local_time = _ph_local(stamp) if stamp else (None, None)
            grouped[key] = {
                "platform": platform,
                "name": platform,
                "acq_date": day,
                "acq_time": hhmm,
                "time_utc": hhmm,
                "acq_datetime_utc": stamp.strftime("%Y-%m-%dT%H:%M:00Z") if stamp else None,
                "acq_date_ph": item.get("acq_date_ph") or local_date,
                "acq_time_ph": item.get("acq_time_ph") or local_time,
                "time_local": (
                    f"{item.get('acq_time_ph') or local_time} PH time"
                    if (item.get("acq_time_ph") or local_time)
                    else None
                ),
                "timezone_label": "PH time",
                "detection_count": 0,
                "members": [],
            }
        grouped[key]["detection_count"] += 1
        grouped[key]["members"].append(item)

    passes = sorted(
        grouped.values(),
        key=lambda row: (row["acq_date"], row["acq_time"], row["platform"]),
    )
    for index in range(1, len(passes)):
        left = _utc_datetime(passes[index - 1]["acq_date"], passes[index - 1]["acq_time"])
        right = _utc_datetime(passes[index]["acq_date"], passes[index]["acq_time"])
        if left and right:
            passes[index]["gap_minutes"] = int(round((right - left).total_seconds() / 60.0))
        else:
            passes[index]["gap_minutes"] = None
    return passes


def _span_minutes(passes: list[dict]) -> int | None:
    if len(passes) < 2:
        return None
    first = _utc_datetime(passes[0]["acq_date"], passes[0]["acq_time"])
    last = _utc_datetime(passes[-1]["acq_date"], passes[-1]["acq_time"])
    if not first or not last:
        return None
    return int(round(abs((last - first).total_seconds()) / 60.0))


def _format_minutes(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rem = divmod(minutes, 60)
    if rem == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} h {rem} min"


def pass_summary(
    members: list[dict] | None,
    *,
    observation_date: str | None = None,
    empty: bool = False,
    coverage_unknown: bool = False,
    scope: str = "square",
) -> dict:
    """Build the selected-square lead from distinct passes."""

    place = "this square" if scope != "drawn_area" else "your drawn area"
    passes = distinct_passes(members, observation_date=observation_date)
    count = len(passes)
    span = _span_minutes(passes)

    if empty and coverage_unknown and count == 0:
        lead = "No heat was reported here. Satellite visibility is unknown."
    elif empty and count == 0:
        lead = "No heat was reported here."
    elif count == 0:
        lead = f"Heat records for {place} could not be grouped into satellite passes."
    elif count == 1:
        lead = "Heat detected once."
    elif count == 2 and span is not None:
        lead = f"Heat detected twice, {_format_minutes(span)} apart."
    elif span is not None:
        lead = f"Heat detected {count} times over {_format_minutes(span)}."
    else:
        lead = f"Heat detected {count} times."

    satellite_rows = [
        {
            "name": row["platform"],
            "time_utc": row["time_utc"],
            "time_local": row.get("time_local"),
            "timezone_label": row.get("timezone_label"),
            "acq_date_ph": row.get("acq_date_ph"),
            "acq_time_ph": row.get("acq_time_ph"),
            "acq_date": row.get("acq_date"),
            "detection_count": row.get("detection_count"),
        }
        for row in passes
    ]

    return {
        "title": "What happened",
        "lead": lead,
        "pass_count": count,
        "span_minutes": span,
        "passes": passes,
        "satellites": satellite_rows,
        "empty": bool(empty or count == 0),
        "coverage_unknown": bool(coverage_unknown),
        "observation_date": observation_date,
        "scope": "Selected 5 km square" if scope != "drawn_area" else "Your drawn area",
        "note": (
            "Distinct passes use spacecraft name plus UTC acquisition time. "
            "Neighboring pixels from one pass count once."
        ),
    }


def confirmation_evidence(*, region: str = "Philippines") -> dict:
    """Honest status for wildfire-confirmation rates among similar alerts."""

    return {
        "question": "How often were similar alerts confirmed as wildfires?",
        "status": "labels_unavailable",
        "region": region,
        "percentage": None,
        "label": None,
        "sample_size": None,
        "verified_count": None,
        "unknown_count": None,
        "date_range": None,
        "uncertainty": None,
        "evaluation_scope": None,
        "match_rules": MATCH_RULES,
        "missing_dataset": MISSING_CONFIRMATION_DATASET,
        "answer": (
            "Vela cannot show a confirmation percentage yet. "
            "No independently verified Philippine wildfire / non-wildfire outcome "
            "labels matched to heat alerts are in this repository."
        ),
        "forbidden_conversions": (
            "Satellite count, FIRMS confidence, weather index, and weekly RF error "
            "are never converted into a wildfire percentage."
        ),
        "future_requirement": (
            "A per-square wildfire probability requires a model validated for that use "
            "on held-out dates and locations, with verified outcomes and reported uncertainty."
        ),
    }
