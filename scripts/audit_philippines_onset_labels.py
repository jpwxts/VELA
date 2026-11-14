"""Audit Philippine wildfire-onset labels before any onset model training.

Usage:
  python -m scripts.audit_philippines_onset_labels
  python -m scripts.audit_philippines_onset_labels --label-dir /tmp/demo --out /tmp/demo/audit.json

Reads actual rows under the label directory via the import path. Counts are
computed from accepted incidents and coverage — never hardcoded.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.onset_labels import import_label_directory, schema_docs
from vela.settings import DATA_DIR
from vela.wildfire_reports import MISSING_DEPENDENCY, lookup_wildfire_report

DEFAULT_DIR = DATA_DIR / "labels" / "philippines_onset"
OUT = DATA_DIR / "metrics" / "philippines_onset_label_audit.json"
BFP_INVESTIGATION = DATA_DIR / "metrics" / "bfp_669031036800_investigation.json"


def _load_bfp_note() -> dict:
    if BFP_INVESTIGATION.is_file():
        return json.loads(BFP_INVESTIGATION.read_text(encoding="utf-8"))
    return {
        "tracking_no": "BFP-669031036800",
        "access_status": "not_investigated",
    }


def build_audit(label_dir: Path, *, synthetic_fixture: bool = False) -> dict:
    sample = lookup_wildfire_report(
        west=124.03,
        south=6.83,
        east=124.09,
        north=6.89,
        date="2026-11-07",
        cell_id="2393:174",
    )
    imported = import_label_directory(label_dir)
    summary = imported.summary()
    bfp = _load_bfp_note()
    positives = [row for row in imported.labeled_square_days if row["label"] == 1]
    dates = sorted({row["issue_date_ph"] for row in positives})
    regions = sorted({row.get("province") or "unknown" for row in positives})
    starts = summary["usable_unique_wildfire_starts"]
    coverage_days = summary["square_days_with_credible_reporting_coverage"]
    negatives_supported = summary["negatives_supported"]
    sufficient = starts > 0 and coverage_days > 0 and negatives_supported
    publish_blocker = None
    if synthetic_fixture:
        publish_blocker = (
            "Synthetic fixture labels are for plumbing tests only. They do not "
            "support production forecasts, analytics, or accuracy claims."
        )
    elif not sufficient:
        publish_blocker = (
            f"{starts} usable unique wildfire starts and {coverage_days} square-days "
            "with credible reporting coverage. "
            + (
                "Negatives are not supported. "
                if not negatives_supported
                else ""
            )
            + "Vela will not publish an onset percentage."
        )

    audit = {
        "title": "Philippine wildfire-onset label audit (Mindanao-first)",
        "audited_at_utc": datetime.now(timezone.utc).isoformat(),
        "label_dir": str(label_dir),
        "synthetic_fixture": synthetic_fixture,
        "target_label": (
            "New wildfire start in a 5 km square during the next Philippine 24 hours"
        ),
        "input_schemas": schema_docs(),
        "import_summary": summary,
        "usable_unique_wildfire_starts": starts,
        "usable_start_dates": dates,
        "usable_regions": regions,
        "square_days_with_credible_reporting_coverage": coverage_days,
        "negatives_supported": negatives_supported,
        "labeled_square_days": summary["labeled_square_days"],
        "rejection_reasons": summary["rejection_reasons"],
        "duplicate_incident_ids": summary["duplicate_incident_ids"],
        "stronger_label_warning": (
            "Only day-precision onset rows with point/barangay locations are accepted "
            "as positives. Report-only dates, ongoing fires, and ambiguous locations "
            "remain unknown."
        ),
        "sources": [
            {
                "name": "Local label directory",
                "path_or_url": str(label_dir),
                "accessible_now": label_dir.is_dir(),
                "usable_unique_wildfire_starts": starts,
                "square_days_with_credible_reporting_coverage": coverage_days,
                "notes": "Counts come from scripts/import_philippines_onset_labels.py.",
            },
            {
                "name": "Vela configured wildfire-report lookup",
                "path_or_url": "vela/wildfire_reports.py",
                "accessible_now": False,
                "usable_unique_wildfire_starts": 0,
                "notes": sample.get("missing_dependency") or MISSING_DEPENDENCY,
            },
            {
                "name": "BFP eFOI BFP-669031036800 Consolidated Forest Fire",
                "path_or_url": bfp.get("request_url"),
                "accessible_now": bfp.get("attachment_accessible") is True,
                "usable_unique_wildfire_starts": bfp.get("usable_unique_wildfire_starts", 0),
                "notes": bfp.get("access_issue") or bfp.get("summary"),
                "investigation_path": str(BFP_INVESTIGATION.relative_to(ROOT))
                if BFP_INVESTIGATION.is_file()
                else None,
            },
            {
                "name": "Davao DENR Region XI referral (separate acquisition lead)",
                "path_or_url": "https://r11.denr.gov.ph/",
                "accessible_now": False,
                "usable_unique_wildfire_starts": 0,
                "notes": (
                    "Separate from BFP-669031036800. Pursue Region XI forest-fire "
                    "microdata only as its own lead; do not treat portal listings as labels."
                ),
            },
        ],
        "publish_blocker": publish_blocker,
        "missing_fields_for_training": []
        if sufficient and not synthetic_fixture
        else [
            "incident_id",
            "onset_date_ph (day precision)",
            "latitude",
            "longitude",
            "reporting_adequate coverage rows for negatives",
        ],
        "next_runnable_step": (
            "Synthetic plumbing only — do not publish."
            if synthetic_fixture
            else (
                "Run python -m scripts.train_philippines_onset"
                if sufficient
                else (
                    "Obtain Mindanao onset + coverage tables (or recover BFP-669031036800 "
                    "attachment when eFOI is back), place under data/labels/philippines_onset/, "
                    "then re-run import and audit."
                )
            )
        ),
        "harmonization_model_untouched": True,
    }
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--synthetic-fixture",
        action="store_true",
        help="Mark this audit as an isolated synthetic plumbing fixture.",
    )
    args = parser.parse_args()
    audit = build_audit(args.label_dir, synthetic_fixture=args.synthetic_fixture)
    out = args.out or (
        OUT if args.label_dir.resolve() == DEFAULT_DIR.resolve() else args.label_dir / "audit.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(out),
                "usable_unique_wildfire_starts": audit["usable_unique_wildfire_starts"],
                "square_days_with_credible_reporting_coverage": audit[
                    "square_days_with_credible_reporting_coverage"
                ],
                "negatives_supported": audit["negatives_supported"],
                "synthetic_fixture": audit["synthetic_fixture"],
                "publish_blocker": audit["publish_blocker"],
                "next_runnable_step": audit["next_runnable_step"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
