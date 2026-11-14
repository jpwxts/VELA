"""Import Philippine wildfire-onset incidents and reporting-coverage tables.

Two input schemas under a label directory (CSV or JSON):

1. incidents — verified new wildfire starts
   Required columns:
     incident_id, onset_date_ph, latitude, longitude
   Optional:
     province, wildfire_class, ongoing, date_precision, location_precision, source
   Rules:
     - onset_date_ph must be a Philippine local calendar day (YYYY-MM-DD) that
       unambiguously identifies the midnight-to-midnight forecast window.
     - location must resolve to exactly one 5 km cell.
     - date_precision=report_only, ongoing=true, or ambiguous location → rejected
       (left unknown; never forced into positives).

2. coverage — area/date reporting coverage for negatives
   Required columns:
     coverage_date_ph, reporting_adequate
   Location (one of):
     cell_id  OR  latitude+longitude  OR  (rejected if ambiguous)
   Optional:
     province, source
   Rules:
     - reporting_adequate must be true/1/yes for a usable negative day.
     - Unmonitored / inadequate days stay unknown (not negatives).

Deduplicates incidents by incident_id (preferred) or by
(onset_date_ph, rounded lat/lon, wildfire_class).
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from vela.grid import cell_identifier, indices

INCIDENT_REQUIRED = ("incident_id", "onset_date_ph", "latitude", "longitude")
COVERAGE_REQUIRED = ("coverage_date_ph", "reporting_adequate")
TRUE_VALUES = {"1", "true", "yes", "y", "t"}
FALSE_VALUES = {"0", "false", "no", "n", "f", ""}


@dataclass
class Rejection:
    kind: str
    reason: str
    row: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportResult:
    incidents_accepted: list[dict[str, Any]] = field(default_factory=list)
    incidents_rejected: list[Rejection] = field(default_factory=list)
    coverage_accepted: list[dict[str, Any]] = field(default_factory=list)
    coverage_rejected: list[Rejection] = field(default_factory=list)
    labeled_square_days: list[dict[str, Any]] = field(default_factory=list)
    duplicate_incident_ids: list[str] = field(default_factory=list)
    schemas: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        positives = [row for row in self.labeled_square_days if row["label"] == 1]
        negatives = [row for row in self.labeled_square_days if row["label"] == 0]
        return {
            "incidents_accepted": len(self.incidents_accepted),
            "incidents_rejected": len(self.incidents_rejected),
            "coverage_accepted": len(self.coverage_accepted),
            "coverage_rejected": len(self.coverage_rejected),
            "usable_unique_wildfire_starts": len(positives),
            "square_days_with_credible_reporting_coverage": len(
                { (row["cell_id"], row["issue_date_ph"]) for row in self.coverage_accepted }
            ),
            "labeled_positives": len(positives),
            "labeled_negatives": len(negatives),
            "labeled_square_days": len(self.labeled_square_days),
            "negatives_supported": len(negatives) > 0,
            "duplicate_incident_ids": self.duplicate_incident_ids,
            "rejection_reasons": _count_reasons(self.incidents_rejected + self.coverage_rejected),
            "schemas": self.schemas,
        }


def _count_reasons(rows: list[Rejection]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        out[row.reason] = out.get(row.reason, 0) + 1
    return out


def _read_table(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "rows" in payload:
            return list(payload["rows"])
        if isinstance(payload, list):
            return payload
        raise ValueError(f"JSON table {path} must be a list or {{'rows': [...]}}.")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _truthy(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def _parse_day(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _cell_from_lat_lon(lat: Any, lon: Any) -> str | None:
    try:
        latitude = float(lat)
        longitude = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    x_index, y_index = indices(longitude, latitude)
    return cell_identifier(int(x_index), int(y_index))


def schema_docs() -> dict[str, Any]:
    return {
        "incidents": {
            "required": list(INCIDENT_REQUIRED),
            "optional": [
                "province",
                "wildfire_class",
                "ongoing",
                "date_precision",
                "location_precision",
                "source",
            ],
            "date_precision_values": ["day", "report_only", "unknown"],
            "location_precision_values": ["point", "barangay", "municipality", "ambiguous"],
            "accept_rule": (
                "Verified Philippine local onset date (day precision) that maps to one "
                "midnight-to-midnight forecast window, location resolves to one 5 km square, "
                "not ongoing, wildfire_class not structural."
            ),
        },
        "coverage": {
            "required": list(COVERAGE_REQUIRED),
            "location_one_of": ["cell_id", "latitude+longitude"],
            "optional": ["province", "source", "latitude", "longitude"],
            "accept_rule": (
                "reporting_adequate=true and location resolves to one 5 km square. "
                "Unmonitored days remain unknown."
            ),
        },
    }


def find_label_files(label_dir: Path) -> dict[str, Path | None]:
    incidents = None
    coverage = None
    for path in sorted(label_dir.glob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.startswith(".") or name == ".gitkeep":
            continue
        if "coverage" in name and path.suffix.lower() in {".csv", ".json"}:
            coverage = path
        elif "incident" in name and path.suffix.lower() in {".csv", ".json"}:
            incidents = path
    return {"incidents": incidents, "coverage": coverage}


def import_incidents(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[Rejection], list[str]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[Rejection] = []
    seen: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for raw in rows:
        row = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        missing = [key for key in INCIDENT_REQUIRED if row.get(key) in (None, "")]
        if missing:
            rejected.append(Rejection("incident", f"missing_fields:{','.join(missing)}", row))
            continue
        onset = _parse_day(row.get("onset_date_ph"))
        if onset is None:
            rejected.append(Rejection("incident", "invalid_onset_date_ph", row))
            continue
        date_precision = str(row.get("date_precision") or "day").strip().lower()
        if date_precision in {"report_only", "unknown"}:
            rejected.append(Rejection("incident", f"date_precision_{date_precision}", row))
            continue
        if date_precision != "day":
            rejected.append(Rejection("incident", f"unsupported_date_precision:{date_precision}", row))
            continue
        location_precision = str(row.get("location_precision") or "point").strip().lower()
        if location_precision in {"ambiguous", "municipality"}:
            rejected.append(Rejection("incident", f"location_precision_{location_precision}", row))
            continue
        ongoing = _truthy(row.get("ongoing"))
        if ongoing is True:
            rejected.append(Rejection("incident", "ongoing_fire_not_new_start", row))
            continue
        wildfire_class = str(row.get("wildfire_class") or "wildfire").strip().lower()
        if wildfire_class in {"structural", "vehicle", "electrical"}:
            rejected.append(Rejection("incident", f"non_wildfire_class:{wildfire_class}", row))
            continue
        cell_id = _cell_from_lat_lon(row.get("latitude"), row.get("longitude"))
        if cell_id is None:
            rejected.append(Rejection("incident", "location_unresolved", row))
            continue
        incident_id = str(row["incident_id"]).strip()
        payload = {
            "incident_id": incident_id,
            "onset_date_ph": onset,
            "issue_date_ph": onset,
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "cell_id": cell_id,
            "province": row.get("province") or None,
            "wildfire_class": wildfire_class,
            "ongoing": False if ongoing is None else bool(ongoing),
            "date_precision": date_precision,
            "location_precision": location_precision,
            "source": row.get("source") or None,
            "label": 1,
        }
        if incident_id in seen:
            duplicates.append(incident_id)
            continue
        # Secondary dedupe key for blank-collision safety across sources.
        geo_key = (
            f"{onset}|{round(payload['latitude'], 4)}|{round(payload['longitude'], 4)}|{wildfire_class}"
        )
        if any(
            f"{item['onset_date_ph']}|{round(item['latitude'], 4)}|{round(item['longitude'], 4)}|{item['wildfire_class']}"
            == geo_key
            for item in accepted
        ):
            duplicates.append(incident_id)
            continue
        seen[incident_id] = payload
        accepted.append(payload)
    return accepted, rejected, duplicates


def import_coverage(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[Rejection]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[Rejection] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        row = {str(k).strip(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        missing = [key for key in COVERAGE_REQUIRED if row.get(key) in (None, "")]
        if missing:
            rejected.append(Rejection("coverage", f"missing_fields:{','.join(missing)}", row))
            continue
        day = _parse_day(row.get("coverage_date_ph"))
        if day is None:
            rejected.append(Rejection("coverage", "invalid_coverage_date_ph", row))
            continue
        adequate = _truthy(row.get("reporting_adequate"))
        if adequate is None:
            rejected.append(Rejection("coverage", "reporting_adequate_unparseable", row))
            continue
        if adequate is False:
            rejected.append(Rejection("coverage", "reporting_inadequate_left_unknown", row))
            continue
        cell_id = str(row.get("cell_id") or "").strip() or None
        if cell_id is None:
            cell_id = _cell_from_lat_lon(row.get("latitude"), row.get("longitude"))
        if cell_id is None:
            rejected.append(Rejection("coverage", "location_unresolved", row))
            continue
        key = (cell_id, day)
        if key in seen:
            continue
        seen.add(key)
        accepted.append(
            {
                "cell_id": cell_id,
                "coverage_date_ph": day,
                "issue_date_ph": day,
                "province": row.get("province") or None,
                "reporting_adequate": True,
                "source": row.get("source") or None,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
            }
        )
    return accepted, rejected


def build_labeled_square_days(
    incidents: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Positives from accepted starts; negatives only on covered days without a start."""

    positives: dict[tuple[str, str], dict[str, Any]] = {}
    for item in incidents:
        key = (item["cell_id"], item["issue_date_ph"])
        # One positive per cell-day even if multiple incidents (rare); keep first id.
        if key not in positives:
            positives[key] = {
                "cell_id": item["cell_id"],
                "issue_date_ph": item["issue_date_ph"],
                "label": 1,
                "province": item.get("province"),
                "incident_id": item["incident_id"],
                "source": item.get("source"),
                "kind": "positive_onset",
            }
    labeled: list[dict[str, Any]] = list(positives.values())
    for item in coverage:
        key = (item["cell_id"], item["issue_date_ph"])
        if key in positives:
            continue
        labeled.append(
            {
                "cell_id": item["cell_id"],
                "issue_date_ph": item["issue_date_ph"],
                "label": 0,
                "province": item.get("province"),
                "incident_id": None,
                "source": item.get("source"),
                "kind": "negative_covered_no_event",
            }
        )
    labeled.sort(key=lambda row: (row["issue_date_ph"], row["cell_id"], row["label"]))
    return labeled


def import_label_directory(label_dir: Path) -> ImportResult:
    label_dir = Path(label_dir)
    result = ImportResult(schemas=schema_docs())
    if not label_dir.is_dir():
        return result
    files = find_label_files(label_dir)
    if files["incidents"] is not None:
        accepted, rejected, duplicates = import_incidents(_read_table(files["incidents"]))
        result.incidents_accepted = accepted
        result.incidents_rejected = rejected
        result.duplicate_incident_ids = duplicates
    if files["coverage"] is not None:
        accepted, rejected = import_coverage(_read_table(files["coverage"]))
        result.coverage_accepted = accepted
        result.coverage_rejected = rejected
    result.labeled_square_days = build_labeled_square_days(
        result.incidents_accepted, result.coverage_accepted
    )
    return result


def import_result_to_jsonable(result: ImportResult) -> dict[str, Any]:
    return {
        "summary": result.summary(),
        "incidents_accepted": result.incidents_accepted,
        "incidents_rejected": [asdict(row) for row in result.incidents_rejected],
        "coverage_accepted": result.coverage_accepted,
        "coverage_rejected": [asdict(row) for row in result.coverage_rejected],
        "labeled_square_days": result.labeled_square_days,
        "imported_at_utc": datetime.utcnow().isoformat() + "Z",
    }
