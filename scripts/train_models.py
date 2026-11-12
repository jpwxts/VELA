"""Fit the comparison only when the paired NASA table is large enough."""

from __future__ import annotations

import json

from vela.settings import DATA_DIR
from vela.train import run_training


def main() -> int:
    report = run_training(DATA_DIR / "processed" / "paired_cells.parquet")
    print(json.dumps({key: report[key] for key in ("data_origin", "chosen_model", "gaps", "counts") if key in report}, indent=2, default=str))
    if report.get("gaps"):
        print("No model was selected. The map still runs without one.")
        for gap in report["gaps"]:
            print(f"- {gap}")
        return 0
    print(f"Chosen from validation: {report['chosen_model']}")
    print(f"Validation: {json.dumps(report['validation'], default=str)}")
    print(f"Temporal test, evaluated once: {json.dumps(report['temporal_test'], default=str)}")
    print(f"Reserved-region evaluation: {json.dumps(report['transfer_evaluation'], default=str)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
