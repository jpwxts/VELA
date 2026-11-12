"""Report whether this Mac can import the science stack and whether logins exist."""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from vela.settings import ROOT


def main() -> int:
    load_dotenv(ROOT / ".env")
    print(f"python: {sys.executable}")
    print(f"python_version: {sys.version.split()[0]}")
    for name in ("pyhdf", "netCDF4", "h5py", "numpy", "pandas", "pyarrow", "sklearn", "fastapi", "earthaccess", "pyproj"):
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: not importable ({exc})")
            continue
        print(f"{name}: {getattr(module, '__version__', 'import ok')}")
    print("firms_map_key_set:", "yes" if os.environ.get("FIRMS_MAP_KEY", "").strip() else "no")
    netrc = Path.home() / ".netrc"
    present = False
    if netrc.is_file():
        for line in netrc.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip() == "machine urs.earthdata.nasa.gov":
                present = True
                break
    print("earthdata_netrc:", "yes" if present else "no")
    free = shutil.disk_usage(ROOT).free
    print(f"disk_free_gb: {free / 1024**3:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
