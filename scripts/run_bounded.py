"""Manifest, catalog, optional one-pass download, then the model check."""

from __future__ import annotations

import argparse

from scripts.make_manifest import main as write_sample
from scripts.smoke_test import run_smoke
from scripts.train_models import main as train


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Vela demo steps in order.")
    parser.add_argument("--download", action="store_true", help="Also download one daytime pass")
    args = parser.parse_args()
    write_sample()
    if args.download:
        smoke_code = run_smoke()
        if smoke_code != 0:
            print("The one-pass download did not finish. Training will report exactly what is missing.")
    else:
        from scripts.catalog_search import search_configured_weeks

        search_configured_weeks()
    return train()


if __name__ == "__main__":
    raise SystemExit(main())
