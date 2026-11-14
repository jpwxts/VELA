"""Import incident + coverage tables from a Philippine onset label directory.

Usage:
  python -m scripts.import_philippines_onset_labels
  python -m scripts.import_philippines_onset_labels --label-dir /tmp/demo --out /tmp/demo/import.json

Default label directory: data/labels/philippines_onset/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.onset_labels import import_label_directory, import_result_to_jsonable
from vela.settings import DATA_DIR

DEFAULT_DIR = DATA_DIR / "labels" / "philippines_onset"
DEFAULT_OUT = DATA_DIR / "metrics" / "philippines_onset_import.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    result = import_label_directory(args.label_dir)
    payload = import_result_to_jsonable(result)
    payload["label_dir"] = str(args.label_dir)
    out = args.out
    if out is None:
        out = DEFAULT_OUT if args.label_dir.resolve() == DEFAULT_DIR.resolve() else args.label_dir / "import.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), **payload["summary"]}, indent=2))


if __name__ == "__main__":
    main()
