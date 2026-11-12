"""Geography helpers that do not assume a particular region."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np


def crosses_dateline(west: float, east: float) -> bool:
    return float(west) > float(east)


def lon_span(west: float, east: float) -> float:
    west = float(west)
    east = float(east)
    if west <= east:
        return east - west
    return (180.0 - west) + (east + 180.0)


def firms_boxes(
    west: float, south: float, east: float, north: float
) -> list[tuple[float, float, float, float]]:
    """Split a rectangle so each piece can be sent to the FIRMS area API.

    FIRMS expects west <= east. A box that crosses the international date
    line is requested as two boxes that meet at longitude 180.
    """

    west, south, east, north = (float(west), float(south), float(east), float(north))
    if west <= east:
        return [(west, south, east, north)]
    return [
        (west, south, 180.0, north),
        (-180.0, south, east, north),
    ]


def in_bbox(lon, lat, west: float, south: float, east: float, north: float):
    lon_arr = np.asarray(lon, dtype=np.float64)
    lat_arr = np.asarray(lat, dtype=np.float64)
    finite = np.isfinite(lon_arr) & np.isfinite(lat_arr)
    plausible = (np.abs(lat_arr) <= 90.0) & (np.abs(lon_arr) <= 180.0)
    lat_ok = (lat_arr >= south) & (lat_arr <= north)
    if west <= east:
        lon_ok = (lon_arr >= west) & (lon_arr <= east)
    else:
        lon_ok = (lon_arr >= west) | (lon_arr <= east)
    return finite & plausible & lat_ok & lon_ok


def boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    if first[3] < second[1] or second[3] < first[1]:
        return False

    def _intervals(west: float, east: float) -> list[tuple[float, float]]:
        if west <= east:
            return [(west, east)]
        return [(west, 180.0), (-180.0, east)]

    for left in _intervals(first[0], first[2]):
        for right in _intervals(second[0], second[2]):
            if left[0] <= right[1] and right[0] <= left[1]:
                return True
    return False


def intersection_area_deg(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """Approximate overlap in square degrees, splitting boxes at the date line."""

    def _pieces(box: tuple[float, float, float, float]):
        west, south, east, north = box
        if west <= east:
            return [(west, south, east, north)]
        return [(west, south, 180.0, north), (-180.0, south, east, north)]

    total = 0.0
    for one in _pieces(first):
        for other in _pieces(second):
            west = max(one[0], other[0])
            south = max(one[1], other[1])
            east = min(one[2], other[2])
            north = min(one[3], other[3])
            if east > west and north > south:
                total += (east - west) * (north - south)
    return total


def box_area_deg(west: float, south: float, east: float, north: float) -> float:
    return max(lon_span(west, east), 0.0) * max(float(north) - float(south), 0.0)


def local_datetime(when: datetime, lon: float) -> datetime:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)
    return when + timedelta(hours=float(lon) / 15.0)


def local_date(when: datetime, lon: float) -> date:
    return local_datetime(when, lon).date()


def local_hour(when: datetime, lon: float) -> float:
    shifted = local_datetime(when, lon)
    return shifted.hour + shifted.minute / 60.0 + shifted.second / 3600.0


def format_hhmm(value) -> str:
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    if not raw:
        return ""
    digits = raw.zfill(4)[-4:]
    if not digits.isdigit():
        return raw
    return f"{digits[:2]}:{digits[2:]}"


def hhmm_digits(value) -> str:
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw.zfill(4)[-4:]


def combine_day_time(day: str, hhmm) -> datetime:
    digits = hhmm_digits(hhmm)
    parsed = datetime.strptime(f"{day} {digits}", "%Y-%m-%d %H%M")
    return parsed.replace(tzinfo=timezone.utc)


def iso_week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def season_of(month: int) -> str:
    if month in (12, 1, 2):
        return "DJF"
    if month in (3, 4, 5):
        return "MAM"
    if month in (6, 7, 8):
        return "JJA"
    return "SON"


def round_box(west: float, south: float, east: float, north: float, places: int = 4):
    return tuple(round(float(value), places) for value in (west, south, east, north))
