"""Open a real MODIS HDF4 file and a real VIIRS NetCDF4/HDF5 file."""

from __future__ import annotations

import argparse
import json

from vela.readers import fire_histogram
from vela.settings import data_dir


def _check(path: str, label: str) -> dict:
    print(f"\nOpening {label}: {path}")
    result = fire_histogram(path)
    print(f"format: {result['format']}")
    print(f"shape: {result['shape']}")
    print(f"pixels_read: {result['pixels']}")
    print(f"class_histogram: {result['histogram']}")
    name = result["file_name"]
    nasa = name.startswith(("MYD14", "VNP14IMG"))
    print("nasa_filename:", "yes" if nasa else "no")
    if not result["opened_array"] or result["pixels"] <= 0:
        raise RuntimeError(f"{label} opened without a readable fire-mask array")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read fire-mask arrays from MODIS HDF4 and VIIRS NetCDF4/HDF5.")
    parser.add_argument("--modis", required=True, help="Path to a MYD14 HDF4 file")
    parser.add_argument("--viirs", required=True, help="Path to a VNP14IMG NetCDF4/HDF5 file")
    args = parser.parse_args()
    modis = _check(args.modis, "MODIS")
    viirs = _check(args.viirs, "VIIRS")
    if modis["format"] != "HDF4":
        raise RuntimeError("The MODIS file did not open as HDF4.")
    if viirs["format"] != "NetCDF4/HDF5":
        raise RuntimeError("The VIIRS file did not open as NetCDF4/HDF5.")
    report = {"modis": modis, "viirs": viirs}
    destination = data_dir("catalog") / "reader_check.json"
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nBoth fire masks were read from the files. Imports alone were not accepted.")
    print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
