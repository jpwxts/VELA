"""Write the NOAA platform-transfer plan. This does not search or download."""

from __future__ import annotations

import json

from vela.platform_transfer import build_plan
from vela.settings import DATA_DIR


def main() -> None:
    plan = build_plan()
    destination = DATA_DIR / "catalog" / "platform_transfer_plan.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(
        f"platform-transfer plan {destination} "
        f"download_started={plan['download_started']} "
        f"measured={plan['measured_transfer_results']}"
    )


if __name__ == "__main__":
    main()
