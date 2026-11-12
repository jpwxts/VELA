"""Fit the 2013–2020 candidate models and leave the saved pilot in place."""

from __future__ import annotations

from scripts.ingest_expansion import PILOT_FILES, _fingerprint
from vela.settings import DATA_DIR
from vela.train import fit_candidates


def main() -> int:
    before = {path.name: _fingerprint(path) for path in PILOT_FILES}
    report = fit_candidates(DATA_DIR / "processed" / "paired_cells.parquet")
    after = {path.name: _fingerprint(path) for path in PILOT_FILES}
    print(f"Training rows: {report.get('counts', {}).get('train_rows')}")
    print(f"Training positives: {report.get('counts', {}).get('train_positives')}")
    print(f"Training years: {report.get('counts', {}).get('train_years')}")
    print(f"Training regions: {report.get('counts', {}).get('train_regions')}")
    print(f"Validation: {report.get('validation')}")
    print(f"Chosen model: {report.get('chosen_model')}")
    if report["gaps"]:
        for gap in report["gaps"]:
            print(gap)
        return 1
    if before != after:
        print("The saved pilot files changed.")
        return 2
    for name, path in report["model_files"].items():
        print(f"Saved {name}: {path}")
    print("Pilot files unchanged.")
    print("2023–2024 and Pantanal were not used for fitting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
