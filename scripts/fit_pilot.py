"""Fit the pilot logistic regression on the paired table already on disk."""

from __future__ import annotations

from vela.pilot import fit_pilot


def main() -> int:
    report = fit_pilot()
    print("Pilot artifact:", report["artifact"])
    print("This is a training diagnostic. It is not the final model and it is not Reveal MODIS.")
    print(
        f"Eligible cells {report['checks']['eligible_cells']}, "
        f"MODIS positives {report['checks']['modis_positives']}, "
        f"duplicate cell-days {report['checks']['duplicate_cell_days']}."
    )
    print("2019-08-23 is omitted from the activity summary.")
    print("Training diagnostics")
    print(f"{'date':<12} {'cells':>7} {'viirs_rate':>12} {'mean_probability':>18} {'modis_rate':>12}")
    for row in report["training_diagnostics"]:
        print(
            f"{row['local_date']:<12} {row['cells']:>7} "
            f"{row['raw_viirs_positive_rate']:>12.4f} "
            f"{row['mean_predicted_probability']:>18.4f} "
            f"{row['observed_modis_positive_rate']:>12.4f}"
        )
    print(
        f"Reloaded probabilities span {report['probability_min']:.6f} to {report['probability_max']:.6f}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
