"""Build compact Mindanao hotspot-forecast cell-day dataset from the observation store."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.hotspot_forecast import freeze_rules
from vela.hotspot_forecast_dataset import build_dataset


def main() -> None:
    freeze_rules()
    result = build_dataset()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
