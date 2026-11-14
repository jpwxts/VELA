"""Check-my-land: forecast fire danger for a plot plus satellite heat evidence.

Forecast danger classes use the documented GWIS Fire Danger Classes table
(FWI thresholds and, when available, local historical ranking percentiles):
https://gwis.jrc.ec.europa.eu/about-gwis/technical-background/fire-danger-forecast

Satellite heat is classified from recorded detection coordinates against the
visitor's polygon. A 5 km display square may cross the boundary; membership
uses the underlying point, not the square.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Iterable

from vela.hotspot_areas import group_hotspot_areas, public_result_summary
from vela.preparedness import explain_day, forecast_point
from vela.wildfire_reports import lookup_wildfire_report

# Documented GWIS Fire Danger Classes (FWI absolute scale).
# Upper bounds are exclusive except the final open-ended class.
GWIS_FWI_CLASSES: tuple[tuple[str, float | None], ...] = (
    ("Low", 11.2),
    ("Moderate", 21.3),
    ("High", 38.0),
    ("Very High", 50.0),
    ("Extreme", 70.0),
    ("Very Extreme", None),
)

# Documented GWIS ranking percentile classes (local historical FWI).
GWIS_RANKING_CLASSES: tuple[tuple[str, float | None], ...] = (
    ("Low", 80.0),
    ("Moderate", 90.0),
    ("High", 95.0),
    ("Very High", 98.0),
    ("Extreme", 99.0),
    ("Very Extreme", None),
)

GWIS_CLASS_SOURCE = (
    "Copernicus GWIS Fire Danger Classes "
    "(https://gwis.jrc.ec.europa.eu/about-gwis/technical-background/fire-danger-forecast). "
    "The headline level uses the published FWI class thresholds. "
    "Local historical ranking is shown as context when GWIS returns it."
)

# GWIS ECMWF FWI forecast grid is documented at about 8 km.
GWIS_GRID_RESOLUTION_KM = 8.0
NEARBY_BUFFER_KM = 5.0

LEVEL_ORDER = {
    "Low": 1,
    "Moderate": 2,
    "High": 3,
    "Very High": 4,
    "Extreme": 5,
    "Very Extreme": 6,
}


def class_from_fwi(fwi: float | None) -> str | None:
    if fwi is None or not (0 <= float(fwi) <= 200):
        return None
    value = float(fwi)
    for name, upper in GWIS_FWI_CLASSES:
        if upper is None or value < upper:
            return name
    return "Very Extreme"


def class_from_ranking(ranking: float | None) -> str | None:
    if ranking is None or not (0 <= float(ranking) <= 100):
        return None
    value = float(ranking)
    for name, upper in GWIS_RANKING_CLASSES:
        if upper is None or value < upper:
            return name
    return "Very Extreme"


def danger_class_for_day(fire: dict | None) -> dict:
    """Attach a documented GWIS class without inventing thresholds."""

    fire = fire or {}
    if fire.get("status") != "measured" or fire.get("fwi") is None:
        return {
            "level": None,
            "basis": "unavailable",
            "fwi": fire.get("fwi"),
            "ranking": fire.get("ranking"),
            "source": GWIS_CLASS_SOURCE,
            "status": fire.get("status") or "unavailable",
        }
    fwi_level = class_from_fwi(fire.get("fwi"))
    ranking_level = class_from_ranking(fire.get("ranking"))
    return {
        "level": fwi_level,
        "basis": "fwi",
        "ranking_level": ranking_level,
        "fwi": fire.get("fwi"),
        "ranking": fire.get("ranking"),
        "source": GWIS_CLASS_SOURCE,
        "status": "measured",
    }


def polygon_bbox(ring: list[list[float]]) -> tuple[float, float, float, float]:
    lons = [float(point[0]) for point in ring]
    lats = [float(point[1]) for point in ring]
    return min(lons), min(lats), max(lons), max(lats)


def normalize_ring(coordinates: Iterable[Iterable[float]]) -> list[list[float]]:
    ring = [[float(lon), float(lat)] for lon, lat in coordinates]
    if len(ring) < 3:
        raise ValueError("A land boundary needs at least three corners.")
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray casting on a closed lon/lat ring. Suitable for small plots."""

    inside = False
    for index in range(len(ring) - 1):
        lon1, lat1 = ring[index]
        lon2, lat2 = ring[index + 1]
        if ((lat1 > lat) != (lat2 > lat)) and (
            lon < (lon2 - lon1) * (lat - lat1) / ((lat2 - lat1) or 1e-15) + lon1
        ):
            inside = not inside
    return inside


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def distance_to_ring_km(lon: float, lat: float, ring: list[list[float]]) -> float:
    if point_in_ring(lon, lat, ring):
        return 0.0
    best = None
    for index in range(len(ring) - 1):
        distance = _distance_to_segment_km(lon, lat, ring[index], ring[index + 1])
        best = distance if best is None else min(best, distance)
    return float(best or 0.0)


def _distance_to_segment_km(
    lon: float, lat: float, start: list[float], end: list[float]
) -> float:
    lon1, lat1 = start
    lon2, lat2 = end
    if lon1 == lon2 and lat1 == lat2:
        return haversine_km(lon, lat, lon1, lat1)
    # Project in local equirectangular meters for short segments.
    mean_lat = math.radians((lat1 + lat2 + lat) / 3.0)
    x = (lon - lon1) * math.cos(mean_lat)
    y = lat - lat1
    dx = (lon2 - lon1) * math.cos(mean_lat)
    dy = lat2 - lat1
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, (x * dx + y * dy) / length2))
    proj_lon = lon1 + t * (lon2 - lon1)
    proj_lat = lat1 + t * (lat2 - lat1)
    return haversine_km(lon, lat, proj_lon, proj_lat)


def polygon_area_km2(ring: list[list[float]]) -> float:
    """Spherical excess approximation for a small closed ring."""

    if len(ring) < 4:
        return 0.0
    total = 0.0
    for index in range(len(ring) - 1):
        lon1 = math.radians(ring[index][0])
        lat1 = math.radians(ring[index][1])
        lon2 = math.radians(ring[index + 1][0])
        lat2 = math.radians(ring[index + 1][1])
        total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(total) * 6371.0 * 6371.0 / 2.0


def format_weekday_safe(day: str) -> str:
    parsed = date.fromisoformat(str(day))
    return parsed.strftime("%A %d %B %Y").lstrip().replace(" 0", " ")


def annotate_forecast_days(forecast: dict) -> dict:
    days = []
    for day in forecast.get("days") or []:
        item = dict(day)
        fire = dict(item.get("fire_danger") or {})
        danger = danger_class_for_day(fire)
        fire["danger_class"] = danger
        item["fire_danger"] = fire
        item["danger_level"] = danger.get("level")
        item["danger_rank"] = LEVEL_ORDER.get(danger.get("level") or "", 0)
        item["explanation"] = land_day_explanation(item)
        days.append(item)
    annotated = dict(forecast)
    annotated["days"] = days
    peak = None
    for day in days:
        if day.get("danger_rank", 0) <= 0:
            continue
        if peak is None or day["danger_rank"] > peak["danger_rank"] or (
            day["danger_rank"] == peak["danger_rank"] and day["valid_date"] < peak["valid_date"]
        ):
            peak = day
    ties = []
    if peak:
        ties = [
            day["valid_date"]
            for day in days
            if day.get("danger_rank") == peak["danger_rank"] and day["valid_date"] != peak["valid_date"]
        ]
    missing = [day["valid_date"] for day in days if not day.get("danger_level")]
    annotated["peak_day"] = peak
    annotated["peak_ties"] = ties
    annotated["missing_days"] = missing
    annotated["danger_class_source"] = GWIS_CLASS_SOURCE
    annotated["grid_resolution_km"] = GWIS_GRID_RESOLUTION_KM
    point = dict(annotated.get("point") or {})
    point["label"] = point.get("label") or "Weather near the center of your selection."
    annotated["point"] = point
    annotated["coverage"] = {
        "mode": "center_point",
        "text": (
            f"Weather near the center of your selection. "
            f"GWIS ECMWF Fire Weather Index cells are about {GWIS_GRID_RESOLUTION_KM:.0f} km across."
        ),
    }
    if annotated.get("regional_fwi_reference") is None:
        from vela.preparedness import regional_fwi_reference

        key = annotated.get("region_key") or ""
        parts = key.split(",")
        if len(parts) == 4:
            try:
                west, south, east, north = (float(part) for part in parts)
            except ValueError:
                west = None
            else:
                annotated["regional_fwi_reference"] = regional_fwi_reference(west, south, east, north)
    annotated["why_this_day"] = why_this_day_copy(annotated)
    weather_ok = any(_weather_day_has_values(day) for day in days)
    values_ok = any(_forecast_day_has_values(day) for day in days)
    annotated["weather_available"] = weather_ok
    annotated["values_available"] = values_ok
    if peak and peak.get("danger_level") == "Low" and peak.get("danger_rank", 0) <= 1:
        # All available classes are Low — do not highlight an arbitrary peak day.
        annotated["headline"] = "Low throughout the available forecast"
        annotated["attention_day"] = None
        annotated["headline_explanation"] = (
            "Every day with a usable Fire Weather Index in this outlook falls in the Low class."
        )
        if missing:
            annotated["headline_explanation"] = (
                annotated["headline_explanation"]
                + f" Fire-danger values are missing for {', '.join(format_weekday_safe(day) for day in missing)}."
            )
    elif peak and peak.get("danger_level"):
        weekday = format_weekday_safe(peak["valid_date"])
        annotated["headline"] = (
            f"{weekday} has the highest forecast fire danger in this outlook: "
            f"{peak['danger_level']}."
        )
        annotated["attention_day"] = peak["valid_date"]
        annotated["headline_explanation"] = peak.get("explanation") or ""
        if ties:
            annotated["headline_explanation"] = (
                (annotated["headline_explanation"] + " ").strip()
                + f" The same peak class is also forecast for {', '.join(format_weekday_safe(day) for day in ties)}."
            )
        if missing:
            annotated["headline_explanation"] = (
                (annotated["headline_explanation"] + " ").strip()
                + f" Fire-danger values are missing for {', '.join(format_weekday_safe(day) for day in missing)}."
            )
    elif weather_ok:
        annotated["headline"] = "Fire-danger forecast unavailable for this location."
        annotated["attention_day"] = days[0]["valid_date"] if days else None
        annotated["headline_explanation"] = (
            "Weather values are available below. GWIS did not return a usable Fire Weather Index "
            "class for these days. This is not an ignition probability."
        )
    elif days and not values_ok:
        annotated["headline"] = "Forecast values unavailable"
        annotated["attention_day"] = None
        annotated["headline_explanation"] = (
            "Dates were returned, but temperature, rainfall, wind, and fire-danger measurements are missing."
        )
    else:
        annotated["headline"] = "Fire-danger forecast unavailable for this location."
        annotated["attention_day"] = None
        annotated["headline_explanation"] = (
            "The weather outlook could not be loaded for this location."
        )
    issued = annotated.get("issued_at")
    product_issue = annotated.get("product_issue_time")
    if product_issue:
        annotated["forecast_status"] = {
            "state": "provider_issue_time",
            "text": f"Provider issue time {product_issue} (UTC).",
            "kind": "provider",
        }
    elif issued:
        annotated["forecast_status"] = {
            "state": "vela_archive_time",
            "text": (
                f"Vela archived this outlook at {_readable_utc(issued)} UTC. "
                "GWIS does not publish a product issue time on this WMS layer."
            ),
            "kind": "archive",
        }
    else:
        annotated["forecast_status"] = {
            "state": "missing_issue_time",
            "text": (
                "Issue time unavailable. GWIS does not publish a product issue time on this WMS layer, "
                "and Vela has not archived this outlook yet."
            ),
            "kind": "missing",
        }
    return annotated


def _weather_day_has_values(day: dict) -> bool:
    for key in (
        "temperature_max_c",
        "relative_humidity_min_percent",
        "wind_speed_max_m_s",
        "forecast_rain_mm",
    ):
        field = day.get(key) or {}
        if field.get("status") in {"measured", "quiet"} and field.get("value") is not None:
            return True
    return False


def _forecast_day_has_values(day: dict) -> bool:
    if _weather_day_has_values(day):
        return True
    fire = day.get("fire_danger") or {}
    return fire.get("status") == "measured" and fire.get("fwi") is not None


def _readable_utc(value: str) -> str:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return stamp.astimezone(timezone.utc).strftime("%d %B %Y at %H:%M").lstrip("0").replace(" 0", " ")


def land_day_explanation(day: dict) -> str:
    fire = day.get("fire_danger") or {}
    danger = fire.get("danger_class") or danger_class_for_day(fire)
    level = danger.get("level")
    parts = []
    if level and fire.get("fwi") is not None:
        parts.append(
            f"GWIS places this day in the {level} fire-danger class "
            f"(Fire Weather Index {float(fire['fwi']):.1f})."
        )
        if fire.get("ranking") is not None:
            ranking_level = danger.get("ranking_level") or class_from_ranking(fire.get("ranking"))
            parts.append(
                f"The local historical ranking is {float(fire['ranking']):.1f}"
                + (f" ({ranking_level} on the ranking scale)" if ranking_level else "")
                + "."
            )
    elif level:
        parts.append(f"GWIS places this day in the {level} fire-danger class.")
    else:
        parts.append("Fire-danger rating unavailable for this day.")

    humidity = day.get("relative_humidity_min_percent") or {}
    wind = day.get("wind_speed_max_km_h") or {}
    if wind.get("value") is None:
        from vela.preparedness import _ms_to_kmh_field

        wind = _ms_to_kmh_field(day.get("wind_speed_max_m_s") or {})
    rain = day.get("forecast_rain_mm") or {}
    direction = day.get("wind_direction_text")
    if humidity.get("status") == "measured" and humidity.get("value") is not None:
        parts.append(f"Minimum relative humidity is forecast at {humidity['value']:.0f}%.")
    if wind.get("status") == "measured" and wind.get("value") is not None:
        parts.append(f"Sustained wind is forecast at {wind['value']:.1f} km/h.")
    if direction:
        parts.append(f"Wind is {direction}.")
    if rain.get("status") in {"measured", "quiet"} and rain.get("value") is not None:
        if float(rain["value"]) == 0:
            parts.append("Forecast rainfall is 0 mm.")
        else:
            parts.append(f"Forecast rainfall is {rain['value']:.1f} mm.")
    elif rain.get("status") == "missing":
        parts.append("Forecast rainfall is missing.")
    return " ".join(parts)


def why_this_day_copy(forecast: dict) -> dict:
    """Plain-English lead for the selected/peak day without wildfire probabilities."""

    days = forecast.get("days") or []
    peak = forecast.get("peak_day")
    selected = peak or (days[0] if days else None)
    if not selected:
        return {
            "lead": "No forecast day is available for this selection yet.",
            "differences": [],
            "missing_note": None,
        }
    level = selected.get("danger_level")
    weekday = format_weekday_safe(selected.get("valid_date") or "")
    if level:
        lead = f"{weekday} has the highest available fire-danger rating near this land: {level}."
        ties = forecast.get("peak_ties") or []
        if ties:
            lead = (
                f"{weekday} ties for the highest available fire-danger rating near this land "
                f"({level}), along with {', '.join(format_weekday_safe(day) for day in ties)}."
            )
    else:
        lead = (
            f"{weekday} is the day shown first because a fire-danger rating is unavailable "
            "for this outlook. Weather values below still come from the forecast."
        )

    differences = []
    wind = selected.get("wind_speed_max_km_h") or {}
    if wind.get("value") is None:
        from vela.preparedness import _ms_to_kmh_field

        wind = _ms_to_kmh_field(selected.get("wind_speed_max_m_s") or {})
    rain = selected.get("forecast_rain_mm") or {}
    other_winds = []
    other_rains = []
    for day in days:
        if day.get("valid_date") == selected.get("valid_date"):
            continue
        other = day.get("wind_speed_max_km_h") or {}
        if other.get("value") is None:
            from vela.preparedness import _ms_to_kmh_field

            other = _ms_to_kmh_field(day.get("wind_speed_max_m_s") or {})
        if other.get("value") is not None:
            other_winds.append(float(other["value"]))
        other_rain = day.get("forecast_rain_mm") or {}
        if other_rain.get("value") is not None:
            other_rains.append(float(other_rain["value"]))
    if wind.get("value") is not None and other_winds:
        avg = sum(other_winds) / len(other_winds)
        delta = float(wind["value"]) - avg
        if abs(delta) >= 3:
            differences.append(
                f"Sustained wind is about {abs(delta):.0f} km/h "
                f"{'stronger' if delta > 0 else 'lighter'} than the other forecast days."
            )
    if rain.get("value") is not None and other_rains:
        avg = sum(other_rains) / len(other_rains)
        delta = float(rain["value"]) - avg
        if float(rain["value"]) == 0 and avg > 0.2:
            differences.append("Forecast rainfall is 0 mm while other days show some rain.")
        elif abs(delta) >= 1:
            differences.append(
                f"Forecast rainfall is about {abs(delta):.1f} mm "
                f"{'wetter' if delta > 0 else 'drier'} than the other forecast days."
            )
    missing = forecast.get("missing_days") or []
    missing_note = None
    if missing:
        missing_note = (
            "Fire-danger ratings are missing for "
            + ", ".join(format_weekday_safe(day) for day in missing)
            + ", so the comparison only uses days with a published rating."
        )
    ranking = (selected.get("fire_danger") or {}).get("ranking")
    if ranking is not None:
        differences.append(
            f"Among local history for this grid cell, today's GWIS ranking is {float(ranking):.0f} "
            "on a 0–100 scale (higher means more unusual for this place and season)."
        )
    return {"lead": lead, "differences": differences[:2], "missing_note": missing_note}


def _detection_inside_or_on_boundary(lon: float, lat: float, ring: list[list[float]]) -> bool:
    return point_in_ring(lon, lat, ring) or distance_to_ring_km(lon, lat, ring) == 0.0


def _detection_inside_geometry(lon: float, lat: float, geometry: dict) -> bool:
    from vela.boundaries import distance_to_geometry_km, point_in_geometry

    return point_in_geometry(lon, lat, geometry) or distance_to_geometry_km(lon, lat, geometry) == 0.0


def filter_payload_to_polygon(
    hotspot_payload: dict,
    ring: list[list[float]] | None = None,
    *,
    geometry: dict | None = None,
) -> dict:
    """Keep FIRMS detections whose coordinates fall inside the visitor polygon.

    The outbound query still uses the padded bounding box; this clip happens before
    5 km area grouping so map markers match the drawn land, not the search box.
    Multipolygon island-group presets pass ``geometry=`` so bbox rings cannot
    pull in Masbate when filtering Mindanao.
    """

    closed = normalize_ring(ring) if ring is not None and geometry is None else None
    filtered_results = []
    total = 0
    for result in hotspot_payload.get("results") or []:
        kept = []
        for spot in result.get("hotspots") or []:
            try:
                lon = float(spot["lon"])
                lat = float(spot["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            if geometry is not None:
                inside = _detection_inside_geometry(lon, lat, geometry)
            else:
                inside = _detection_inside_or_on_boundary(lon, lat, closed or [])
            if inside:
                kept.append(spot)
        total += len(kept)
        filtered_results.append({**result, "hotspots": kept, "count": len(kept)})
    return {
        **hotspot_payload,
        "results": filtered_results,
        "total_count": total,
        "polygon_filtered": True,
    }


def feed_breakdown(hotspot_payload: dict, inside_rows: list[dict]) -> list[dict]:
    """Compact per-satellite lines for the selected polygon."""

    inside_counts: dict[str, int] = {}
    for row in inside_rows:
        platform = str(row.get("platform") or "Unrecognized")
        inside_counts[platform] = inside_counts.get(platform, 0) + 1

    lines = []
    for result in hotspot_payload.get("results") or []:
        platform = str(result.get("platform") or "Unrecognized")
        status = result.get("status") or "unknown"
        count = int(inside_counts.get(platform, 0))
        if status == "product_unavailable":
            lines.append(
                {
                    "platform": platform,
                    "status": "unavailable",
                    "count": 0,
                    "text": f"{platform} · unavailable for this date",
                }
            )
        elif status == "request_failed":
            lines.append(
                {
                    "platform": platform,
                    "status": "failed",
                    "count": 0,
                    "text": f"{platform} · request failed",
                }
            )
        elif status not in {"ok", "no_hotspots"}:
            lines.append({"platform": platform, "status": "unavailable", "count": 0,
                          "text": f"{platform} · feed unavailable ({status})"})
        elif count == 0:
            lines.append(
                {
                    "platform": platform,
                    "status": "zero",
                    "count": 0,
                    "text": f"{platform} · 0 detections inside the boundary",
                }
            )
        else:
            lines.append(
                {
                    "platform": platform,
                    "status": "ok",
                    "count": count,
                    "text": f"{platform} · {count} detection{'s' if count != 1 else ''}",
                }
            )
    return lines


def classify_detections(
    hotspot_payload: dict,
    ring: list[list[float]] | None = None,
    nearby_km: float = NEARBY_BUFFER_KM,
    *,
    geometry: dict | None = None,
) -> dict:
    if geometry is None and ring is None:
        raise TypeError("classify_detections requires ring or geometry")
    closed = normalize_ring(ring) if ring is not None and geometry is None else None
    if geometry is not None:
        from vela.boundaries import distance_to_geometry_km

        def _inside(lon: float, lat: float) -> bool:
            return _detection_inside_geometry(lon, lat, geometry)

        def _distance(lon: float, lat: float) -> float:
            return distance_to_geometry_km(lon, lat, geometry)

    else:
        assert closed is not None

        def _inside(lon: float, lat: float) -> bool:
            return _detection_inside_or_on_boundary(lon, lat, closed)

        def _distance(lon: float, lat: float) -> float:
            return distance_to_ring_km(lon, lat, closed)

    # Prefer raw records so a 5 km square that straddles the fence does not mis-label.
    records = []
    for result in hotspot_payload.get("results") or []:
        for spot in result.get("hotspots") or []:
            item = dict(spot)
            item.setdefault("source", result.get("product"))
            item.setdefault("platform", spot.get("platform") or result.get("platform"))
            records.append(item)

    inside = []
    nearby = []
    for spot in records:
        lon = float(spot["lon"])
        lat = float(spot["lat"])
        distance = _distance(lon, lat)
        row = {
            "lat": lat,
            "lon": lon,
            "platform": spot.get("platform") or "Unrecognized",
            "acq_date": spot.get("acq_date"),
            "acq_time": spot.get("acq_time") or spot.get("acq_time_raw"),
            "acq_time_raw": spot.get("acq_time_raw") or spot.get("acq_time"),
            "confidence": spot.get("confidence"),
            "frp": spot.get("frp"),
            "source": spot.get("source"),
            "distance_km": round(distance, 2),
        }
        if _inside(lon, lat):
            row["relation"] = "inside"
            inside.append(row)
        elif distance <= nearby_km:
            row["relation"] = "nearby"
            nearby.append(row)

    inside.sort(key=lambda item: (item.get("acq_date") or "", item.get("acq_time") or ""))
    nearby.sort(key=lambda item: (item["distance_km"], item.get("acq_date") or "", item.get("acq_time") or ""))

    # Map markers / area grouping use only detections retained inside the polygon.
    filtered_payload = filter_payload_to_polygon(hotspot_payload, closed, geometry=geometry)
    areas = group_hotspot_areas(filtered_payload)

    results = hotspot_payload.get("results") or []
    if not results:
        coverage = "unknown"
    elif all((result.get("coverage") or "unknown") == "unknown" for result in results):
        coverage = "unknown"
    elif any((result.get("coverage") or "unknown") == "unknown" for result in results):
        coverage = "mixed"
    else:
        coverage = "observed"

    succeeded = [row for row in results if row.get("status") in {"ok", "no_hotspots"}]
    failed = [row for row in results if row.get("status") not in {"ok", "no_hotspots"}]
    latest_pass_ph = None
    if inside:
        from zoneinfo import ZoneInfo
        latest = inside[-1]
        try:
            time_text = str(latest['acq_time'])
            if ':' not in time_text:
                digits = time_text.zfill(4)
                time_text = f"{digits[:2]}:{digits[2:]}"
            stamp = datetime.fromisoformat(f"{latest['acq_date']}T{time_text}:00+00:00")
            latest_pass_ph = stamp.astimezone(ZoneInfo("Asia/Manila")).isoformat()
        except (ValueError, KeyError):
            pass
        satellite_count = len({row["platform"] for row in inside})
        square_count = int((areas or {}).get("area_count") or 0)
        lead = (f"{len(inside)} satellite heat readings in {square_count} squares "
                f"from {satellite_count} satellites.")
        if latest_pass_ph:
            lead += f" Latest Philippine-time pass: {latest_pass_ph}."
        if failed:
            lead += " Some feeds failed or are unavailable; see feed details."
        status = "inside"
    elif not succeeded:
        lead = "Satellite heat search unavailable: no feed completed successfully. Clear-view coverage is unknown."
        status = "unavailable"
    else:
        lead = "No satellite heat readings returned for this search inside your boundary. "
        lead += "Clear-view coverage is unknown." if coverage == "unknown" else f"Clear-view coverage: {coverage}."
        if nearby:
            lead += f" {len(nearby)} readings returned nearby, outside the boundary."
        if failed:
            lead += " Some feeds failed or are unavailable; see feed details."
        status = "nearby_only" if nearby else ("none_unknown" if coverage == "unknown" else "none")

    platforms_inside = sorted({row["platform"] for row in inside})
    platforms_nearby = sorted({row["platform"] for row in nearby})
    return {
        "status": status,
        "lead": lead,
        "inside_count": len(inside),
        "search_complete": bool(succeeded) and not failed,
        "latest_pass_ph": latest_pass_ph,
        "failed_feeds": [row.get("platform") for row in failed],
        "nearby_count": len(nearby),
        "nearby_buffer_km": nearby_km,
        "inside": inside,
        "nearby": nearby,
        "platforms_inside": platforms_inside,
        "platforms_nearby": platforms_nearby,
        "coverage": coverage,
        "feeds": feed_breakdown(hotspot_payload, inside),
        "areas": (areas or {}).get("areas") if isinstance(areas, dict) else [],
        "hotspot_areas": areas if isinstance(areas, dict) else None,
        "public_result": public_result_summary(filtered_payload, areas),
    }


def build_land_check(
    *,
    ring: list[list[float]],
    forecast: dict,
    hotspot_payload: dict,
    label: str | None = None,
    observation_date: str | None = None,
    fixture: dict | None = None,
    geometry: dict | None = None,
) -> dict:
    closed = normalize_ring(ring)
    west, south, east, north = polygon_bbox(closed)
    annotated = annotate_forecast_days(forecast)
    heat = classify_detections(hotspot_payload, closed, geometry=geometry)
    area_km2 = polygon_area_km2(closed)
    wildfire = lookup_wildfire_report(
        west=west,
        south=south,
        east=east,
        north=north,
        date=observation_date or "",
    )
    if wildfire.get("status") == "matched":
        incident_line = (
            f"Reported incident · {wildfire.get('agency')} · {wildfire.get('incident_name')} · "
            f"{wildfire.get('incident_date')}"
        )
    elif wildfire.get("status") == "searched_none":
        incident_line = f"Reported incident · No matching report found in {wildfire.get('source')}."
    else:
        incident_line = "Reported incident · Vela has no wildfire-report data for this location."

    center_lat, center_lon = forecast_point(west, south, east, north)
    # Harmonized weekly activity + reliability for the land summary card.
    from vela.findings import reliability_block

    from vela.history import build_monthly_history
    from vela.observation_store import philippine_today

    selected_day = date.fromisoformat(observation_date or philippine_today().isoformat())
    history = build_monthly_history(closed, selected_day.year, selected_day.month, today=philippine_today(), geometry=geometry)
    activity = next((row for row in history["days"] if row["date"] == selected_day.isoformat()), {})
    if activity.get("activity_rate") is None:
        activity = {**activity, "status": "unavailable",
                    "missing_input": "Eligible Aqua fire-mask/geolocation or calibrated Suomi-NPP cell-day contributions",
                    "explanation": "No eligible coverage-based contribution for this boundary and Philippine date."}
    reliability = reliability_block()
    return {
        "ok": True,
        "label": label or "Your land",
        "polygon": {"type": "Polygon", "coordinates": [closed]},
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "area_km2": round(area_km2, 2),
        "observation_date": observation_date,
        "forecast": annotated,
        "heat": heat,
        "activity": activity,
        "reliability": reliability,
        "incident": {"line": incident_line, **wildfire},
        "questions": {
            "forecast_danger": annotated.get("headline"),
            "attention_day": annotated.get("attention_day"),
            "satellite_heat": heat.get("lead"),
        },
        "separation_note": (
            "Forecast fire danger, satellite heat detections, and agency incident reports "
            "answer different questions. They are shown together and are not combined into a score."
        ),
        "center": {"lat": center_lat, "lon": center_lon},
        "fixture": fixture,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
