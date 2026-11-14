"""End-to-end onset plumbing with isolated synthetic incidents + coverage."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from vela.grid import cell_identifier, indices
from vela.onset_labels import import_label_directory

ROOT = Path(__file__).resolve().parents[1]


def _cell(lat: float, lon: float) -> str:
    x_index, y_index = indices(lon, lat)
    return cell_identifier(int(x_index), int(y_index))


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_synthetic_label_dir(base: Path) -> Path:
    """Clearly marked synthetic fixture: never for production serving."""

    label_dir = base / "synthetic_philippines_onset"
    # Maguindanao train cell
    lat_t, lon_t = 6.85779, 124.05852
    cell_t = _cell(lat_t, lon_t)
    # Bukidnon validation-ish point
    lat_v, lon_v = 8.15, 125.08
    cell_v = _cell(lat_v, lon_v)
    # Davao test point
    lat_s, lon_s = 7.19, 125.45
    cell_s = _cell(lat_s, lon_s)

    incidents = []
    # Known positive (train) + exact duplicate id should count once.
    incidents.append(
        {
            "incident_id": "SYN-POS-1",
            "onset_date_ph": "2023-03-01",
            "latitude": lat_t,
            "longitude": lon_t,
            "province": "Maguindanao del Norte",
            "wildfire_class": "wildfire",
            "ongoing": "false",
            "date_precision": "day",
            "location_precision": "point",
            "source": "synthetic_fixture",
        }
    )
    incidents.append(dict(incidents[0]))  # duplicate
    # Extra train positives/negatives via more start days
    for day, idx in [("2023-03-05", 2), ("2023-03-10", 3), ("2023-04-01", 4), ("2023-05-01", 5)]:
        incidents.append(
            {
                "incident_id": f"SYN-POS-{idx}",
                "onset_date_ph": day,
                "latitude": lat_t + 0.01 * idx,
                "longitude": lon_t + 0.01 * idx,
                "province": "Maguindanao del Norte",
                "wildfire_class": "wildfire",
                "ongoing": "false",
                "date_precision": "day",
                "location_precision": "point",
                "source": "synthetic_fixture",
            }
        )
    # Validation positives
    for day, idx in [("2024-02-01", 6), ("2024-03-01", 7), ("2024-04-01", 8)]:
        incidents.append(
            {
                "incident_id": f"SYN-POS-{idx}",
                "onset_date_ph": day,
                "latitude": lat_v,
                "longitude": lon_v + 0.01 * (idx - 5),
                "province": "Bukidnon",
                "wildfire_class": "wildfire",
                "ongoing": "false",
                "date_precision": "day",
                "location_precision": "point",
                "source": "synthetic_fixture",
            }
        )
    # Test positives
    for day, idx in [("2025-01-10", 9), ("2025-02-10", 10), ("2025-03-10", 11)]:
        incidents.append(
            {
                "incident_id": f"SYN-POS-{idx}",
                "onset_date_ph": day,
                "latitude": lat_s,
                "longitude": lon_s + 0.01 * (idx - 8),
                "province": "Davao del Norte",
                "wildfire_class": "wildfire",
                "ongoing": "false",
                "date_precision": "day",
                "location_precision": "point",
                "source": "synthetic_fixture",
            }
        )
    # Rejected: report-only, ongoing, ambiguous
    incidents.append(
        {
            "incident_id": "SYN-REJECT-REPORT",
            "onset_date_ph": "2023-06-01",
            "latitude": lat_t,
            "longitude": lon_t,
            "province": "Maguindanao del Norte",
            "wildfire_class": "wildfire",
            "ongoing": "false",
            "date_precision": "report_only",
            "location_precision": "point",
            "source": "synthetic_fixture",
        }
    )
    incidents.append(
        {
            "incident_id": "SYN-REJECT-ONGOING",
            "onset_date_ph": "2023-06-02",
            "latitude": lat_t,
            "longitude": lon_t,
            "province": "Maguindanao del Norte",
            "wildfire_class": "wildfire",
            "ongoing": "true",
            "date_precision": "day",
            "location_precision": "point",
            "source": "synthetic_fixture",
        }
    )

    coverage = []
    # Covered no-event negatives (train/val/test)
    for day in [
        "2023-03-02",
        "2023-03-06",
        "2023-03-11",
        "2023-04-02",
        "2023-05-02",
        "2023-05-03",
        "2023-05-04",
        "2023-05-05",
    ]:
        coverage.append(
            {
                "cell_id": cell_t,
                "coverage_date_ph": day,
                "reporting_adequate": "true",
                "province": "Maguindanao del Norte",
                "source": "synthetic_fixture",
            }
        )
    for day in ["2024-02-02", "2024-03-02", "2024-04-02", "2024-04-03", "2024-04-04"]:
        coverage.append(
            {
                "cell_id": cell_v,
                "coverage_date_ph": day,
                "reporting_adequate": "true",
                "province": "Bukidnon",
                "source": "synthetic_fixture",
            }
        )
    for day in ["2025-01-11", "2025-02-11", "2025-03-11", "2025-03-12"]:
        coverage.append(
            {
                "cell_id": cell_s,
                "coverage_date_ph": day,
                "reporting_adequate": "true",
                "province": "Davao del Norte",
                "source": "synthetic_fixture",
            }
        )
    # Inadequate coverage stays unknown (rejected from negatives)
    coverage.append(
        {
            "cell_id": cell_t,
            "coverage_date_ph": "2023-07-01",
            "reporting_adequate": "false",
            "province": "Maguindanao del Norte",
            "source": "synthetic_fixture",
        }
    )

    _write_csv(label_dir / "incidents_synthetic.csv", incidents)
    _write_csv(label_dir / "coverage_synthetic.csv", coverage)
    (label_dir / "README_SYNTHETIC.txt").write_text(
        "SYNTHETIC FIXTURE ONLY — not for production forecasts or accuracy claims.\n",
        encoding="utf-8",
    )
    # Unmonitored day intentionally omitted from coverage and incidents: 2023-08-15
    return label_dir


def test_import_dedup_negative_and_unknown(tmp_path: Path):
    label_dir = build_synthetic_label_dir(tmp_path)
    result = import_label_directory(label_dir)
    summary = result.summary()
    assert "SYN-POS-1" in summary["duplicate_incident_ids"]
    positives = [row for row in result.labeled_square_days if row["label"] == 1]
    assert sum(1 for row in positives if row["incident_id"] == "SYN-POS-1") == 1
    negatives = [row for row in result.labeled_square_days if row["label"] == 0]
    assert any(row["issue_date_ph"] == "2023-03-02" and row["label"] == 0 for row in negatives)
    # Unmonitored day absent
    assert not any(row["issue_date_ph"] == "2023-08-15" for row in result.labeled_square_days)
    assert any(rej.reason == "date_precision_report_only" for rej in result.incidents_rejected)
    assert any(rej.reason == "ongoing_fire_not_new_start" for rej in result.incidents_rejected)
    assert any(rej.reason == "reporting_inadequate_left_unknown" for rej in result.coverage_rejected)


def test_normal_commands_import_audit_train_evaluate(tmp_path: Path):
    label_dir = build_synthetic_label_dir(tmp_path)
    work = tmp_path / "run"
    work.mkdir()
    import_out = work / "import.json"
    audit_out = work / "audit.json"
    split_out = work / "split.json"
    # Seed split rules from production manifest (counts overwritten by train).
    split_out.write_text(
        (ROOT / "data" / "manifests" / "philippines_onset_split.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    comparison_out = work / "comparison.json"
    selection_out = work / "selection.json"
    eval_out = work / "holdout.json"
    model_dir = work / "models"

    def run(args: list[str]) -> dict:
        completed = subprocess.run(
            [sys.executable, "-m", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    imp = run(
        [
            "scripts.import_philippines_onset_labels",
            "--label-dir",
            str(label_dir),
            "--out",
            str(import_out),
        ]
    )
    assert imp["usable_unique_wildfire_starts"] >= 1
    assert imp["labeled_negatives"] >= 1

    audit = run(
        [
            "scripts.audit_philippines_onset_labels",
            "--label-dir",
            str(label_dir),
            "--out",
            str(audit_out),
            "--synthetic-fixture",
        ]
    )
    assert audit["synthetic_fixture"] is True
    assert audit["usable_unique_wildfire_starts"] == imp["usable_unique_wildfire_starts"]

    train = run(
        [
            "scripts.train_philippines_onset",
            "--label-dir",
            str(label_dir),
            "--audit",
            str(audit_out),
            "--comparison-out",
            str(comparison_out),
            "--selection-out",
            str(selection_out),
            "--split-out",
            str(split_out),
            "--model-dir",
            str(model_dir),
            "--allow-synthetic-research",
        ]
    )
    assert train["status"] == "research_trained"
    assert train["winner"]
    assert train["approved_for_serving"] is False
    assert train["row_counts"]["test"] >= 1

    evaluation = run(
        [
            "scripts.evaluate_philippines_onset",
            "--label-dir",
            str(label_dir),
            "--selection",
            str(selection_out),
            "--split",
            str(split_out),
            "--out",
            str(eval_out),
            "--audit",
            str(audit_out),
        ]
    )
    assert evaluation["status"] == "holdout_evaluated"
    assert evaluation["holdout_rows"] >= 1
    assert evaluation["metrics"] is not None
    assert evaluation["metrics"]["positive_event_count"] >= 0
    assert evaluation["approved_for_serving"] is False
    # Production publish path remains blocked for synthetic audits.
    from vela.onset_forecast import forecast_for_cell, load_audit

    audit_payload = load_audit(audit_out)
    assert audit_payload["synthetic_fixture"] is True
    served = forecast_for_cell(cell_id=_cell(6.85779, 124.05852), issue_date="2023-03-01")
    # Default production audit still governs serving unless tests monkeypatch;
    # ensure synthetic selection cannot approve serving.
    selection = json.loads(selection_out.read_text(encoding="utf-8"))
    assert selection["approved_for_serving"] is False
    assert selection["state"] == "holdout_evaluated"
