"""Reread one saved pass and write the VIIRS-only and MODIS-only cell traces."""

from __future__ import annotations

from vela.traces import build_examples


def main() -> int:
    payload = build_examples()
    for example in payload["examples"]:
        check = example["zero_check"]
        print(
            f"{example['outcome']} {example['cell_id']} "
            f"shared {example['shared_coverage_fraction']:.2f} "
            f"clear {check['clear_land_pixels']} fire {check['fire_pixels']}"
        )
        print(check["text"])
    print(f"Wrote traces for {payload['source_pass']['local_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
