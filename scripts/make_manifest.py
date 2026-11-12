"""Write the week sample before any granule is downloaded."""

from __future__ import annotations

from collections import Counter

from vela.sample import build_manifest, write_manifest


def main() -> int:
    rows = build_manifest()
    path = write_manifest(rows)
    roles = Counter(row["role"] for row in rows)
    quiet = sum(1 for row in rows if row["quiet"] == "yes")
    splits = Counter(row["split"] for row in rows)
    print(f"Wrote {path}")
    print(f"Weeks: {len(rows)}")
    print(f"Roles: {dict(roles)}")
    print(f"Quiet weeks: {quiet}")
    print(f"Year splits: {dict(splits)}")
    print("No files were downloaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
