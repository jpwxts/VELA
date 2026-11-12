"""Independent wildfire-incident lookup for the public area panel.

Satellite heat detections are not wildfire confirmations. This module only reports
a match when a verified incident source is configured and successfully searched.
No probability is derived from satellite counts, FIRMS confidence, or model scores.
"""

from __future__ import annotations

MISSING_DEPENDENCY = (
    "No verified wildfire-incident source is configured for Vela yet "
    "(for example an agency incident feed with location and date)."
)


def lookup_wildfire_report(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    date: str,
    cell_id: str | None = None,
) -> dict:
    """Return the most honest wildfire-report state for a selected square and day."""

    _ = (west, south, east, north, date, cell_id)
    return {
        "status": "unavailable",
        "text": "Vela has no wildfire-report data for this location.",
        "source": None,
        "agency": None,
        "incident_name": None,
        "incident_date": None,
        "url": None,
        "missing_dependency": MISSING_DEPENDENCY,
        "derived_from_satellites": False,
    }
