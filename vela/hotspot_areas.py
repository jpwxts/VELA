"""Group FIRMS hotspot records into 5 km heat-detection areas.

An observation day is the FIRMS acquisition date in UTC (`acq_date`). Areas are
labeled as places with detected heat, never as a count of wildfires. Spacecraft
counts use the identified platform on each record so a mixed MODIS feed can still
separate Aqua from Terra.
"""

from __future__ import annotations

from collections import defaultdict

from vela.grid import cell_identifier, center, geographic_bounds, indices
from vela.settings import settings

OBSERVATION_DAY_LABEL = (
    "Observation day is the FIRMS acquisition date in UTC (acq_date). "
    "It is not a local calendar day and not a wildfire-incident day."
)


def _record_identity(spot: dict) -> tuple:
    return (
        round(float(spot["lat"]), 5),
        round(float(spot["lon"]), 5),
        str(spot.get("acq_date") or ""),
        str(spot.get("acq_time_raw") or spot.get("acq_time") or ""),
        str(spot.get("satellite_code") or ""),
        str(spot.get("instrument") or ""),
        str(spot.get("platform") or ""),
        spot.get("frp"),
        spot.get("brightness"),
    )


def _dedupe(records: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for spot in records:
        identity = _record_identity(spot)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(spot)
    return unique


def collect_hotspots(payload: dict) -> list[dict]:
    records = []
    for result in payload.get("results") or []:
        for spot in result.get("hotspots") or []:
            item = dict(spot)
            item.setdefault("source", result.get("product"))
            item.setdefault("feed_status", result.get("status"))
            records.append(item)
    return _dedupe(records)


def group_hotspot_areas(payload: dict) -> dict:
    """Build zoom-stable 5 km areas from returned detection records."""

    records = collect_hotspots(payload)
    day = str(payload.get("date") or "")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for spot in records:
        observation_day = str(spot.get("acq_date") or day)
        x_index, y_index = indices(float(spot["lon"]), float(spot["lat"]))
        cell_id = cell_identifier(int(x_index), int(y_index))
        groups[(cell_id, observation_day)].append(spot)

    areas = []
    multi = 0
    for (cell_id, observation_day), members in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        x_text, y_text = cell_id.split(":", 1)
        x_index, y_index = int(x_text), int(y_text)
        lon, lat = center(x_index, y_index)
        west, south, east, north = geographic_bounds(x_index, y_index)
        platforms = sorted({str(item.get("platform") or "Unrecognized") for item in members})
        passes = sorted(
            {
                (
                    str(item.get("platform") or "Unrecognized"),
                    str(item.get("acq_date") or ""),
                    str(item.get("acq_time") or item.get("acq_time_raw") or ""),
                )
                for item in members
            }
        )
        by_platform = []
        for platform in platforms:
            platform_members = [item for item in members if str(item.get("platform") or "Unrecognized") == platform]
            times = sorted({str(item.get("acq_time") or item.get("acq_time_raw") or "") for item in platform_members})
            by_platform.append(
                {
                    "platform": platform,
                    "detection_count": len(platform_members),
                    "observation_times_utc": times,
                    "passes": len({(item.get("acq_date"), item.get("acq_time") or item.get("acq_time_raw")) for item in platform_members}),
                }
            )
        satellite_count = len(platforms)
        if satellite_count > 1:
            multi += 1
        areas.append(
            {
                "cell_id": cell_id,
                "observation_day": observation_day,
                "observation_day_convention": OBSERVATION_DAY_LABEL,
                "center_lat": lat,
                "center_lon": lon,
                "bounds": {"west": west, "south": south, "east": east, "north": north},
                "area_km2": float(settings()["cell_area_km2"]),
                "label": "area with detected heat",
                "satellite_count": satellite_count,
                "detection_count": len(members),
                "pass_count": len(passes),
                "platforms": platforms,
                "by_platform": by_platform,
                "members": members,
                "multiple_satellites": satellite_count > 1,
            }
        )

    satellites = sorted({str(spot.get("platform") or "Unrecognized") for spot in records})
    return {
        "observation_day_convention": OBSERVATION_DAY_LABEL,
        "grid": "5 km equal-area cells",
        "area_count": len(areas),
        "detection_count": len(records),
        "satellite_count": len(satellites),
        "satellites": satellites,
        "multiple_satellite_area_count": multi,
        "one_satellite_area_count": len(areas) - multi,
        "areas": areas,
        "not_a_wildfire_count": True,
    }


DEFAULT_PUBLIC_PLATFORMS = ("Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21")
STATUS_PLATFORM_ORDER = ("Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21")


def public_result_summary(payload: dict, areas: dict) -> dict:
    """One short public result computed from the FIRMS response and area groups."""

    combined = payload.get("combined") or {}
    coverage = combined.get("coverage") or "unknown"
    area_count = int(areas.get("area_count") or 0)
    detection_count = int(areas.get("detection_count") or 0)
    satellite_count = int(areas.get("satellite_count") or 0)
    multi = int(areas.get("multiple_satellite_area_count") or 0)
    if coverage == "unknown" and detection_count == 0:
        text = (
            "No detections were returned. We don’t know how much of this area the satellites observed."
        )
        kind = "unknown_empty"
        lead = text
    elif area_count == 0:
        text = "Satellites detected heat in 0 areas."
        kind = "empty"
        lead = text
    elif area_count == 1:
        text = "Satellites detected heat in 1 area."
        kind = "with_detections" if coverage != "unknown" else "unknown_with_detections"
        lead = text
    else:
        text = f"Satellites detected heat in {area_count} areas."
        kind = "with_detections" if coverage != "unknown" else "unknown_with_detections"
        lead = text
    return {
        "kind": kind,
        "text": text,
        "lead": lead,
        "multi_line": (
            f"{multi} area{'s' if multi != 1 else ''} {'were' if multi != 1 else 'was'} "
            f"seen by more than one satellite."
            if multi
            else (
                "Each area was reported by one satellite."
                if area_count
                else ""
            )
        ),
        "area_count": area_count,
        "detection_count": detection_count,
        "satellite_count": satellite_count,
        "multiple_satellite_area_count": multi,
        "coverage": coverage,
    }


def platform_status_for_cell(payload: dict, cell_id: str | None, observation_day: str | None = None) -> list[dict]:
    """Most specific public state for each spacecraft in one 5 km square and day.

    Clear-view zeros require measured usable coverage. FIRMS hotspot feeds alone do
    not establish that, so an empty return stays “clear view unknown,” never zero.
    """

    results = {row.get("platform"): row for row in (payload.get("results") or []) if row.get("platform")}
    areas = ((payload.get("hotspot_areas") or {}).get("areas")) or []
    matched = None
    for area in areas:
        if cell_id and area.get("cell_id") == cell_id:
            if observation_day and area.get("observation_day") != observation_day:
                continue
            matched = area
            break
    day = observation_day or (matched or {}).get("observation_day") or payload.get("date")
    statuses = []
    for platform in STATUS_PLATFORM_ORDER:
        feed = results.get(platform)
        if feed is None:
            statuses.append(
                {
                    "platform": platform,
                    "state": "not_included",
                    "text": "Not included in your search.",
                    "times_utc": [],
                }
            )
            continue
        if feed.get("status") == "product_unavailable":
            statuses.append(
                {
                    "platform": platform,
                    "state": "data_unavailable",
                    "text": "Data unavailable for this date.",
                    "times_utc": [],
                }
            )
            continue
        if feed.get("status") == "request_failed":
            statuses.append(
                {
                    "platform": platform,
                    "state": "data_unavailable",
                    "text": "Data unavailable for this date.",
                    "times_utc": [],
                }
            )
            continue
        by_platform = {row["platform"]: row for row in ((matched or {}).get("by_platform") or [])}
        if platform in by_platform:
            times = list(by_platform[platform].get("observation_times_utc") or [])
            if len(times) == 1:
                text = f"Detected heat at {times[0]} UTC."
            elif times:
                text = "Detected heat at " + "; ".join(f"{time} UTC" for time in times) + "."
            else:
                text = "Detected heat."
            statuses.append(
                {
                    "platform": platform,
                    "state": "detected",
                    "text": text,
                    "times_utc": times,
                }
            )
            continue
        coverage = feed.get("coverage") or "unknown"
        if coverage != "unknown" and feed.get("status") in {"ok", "no_hotspots"}:
            statuses.append(
                {
                    "platform": platform,
                    "state": "observed_no_heat",
                    "text": "Observed this area. No heat detected during this pass.",
                    "times_utc": [],
                    "observation_day": day,
                }
            )
        else:
            statuses.append(
                {
                    "platform": platform,
                    "state": "no_detection_unknown",
                    "text": "No detection returned. Clear view unknown.",
                    "times_utc": [],
                    "observation_day": day,
                }
            )
    return statuses
