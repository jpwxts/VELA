"""Dry-run and same-filesystem quarantine for overseas raw granules.

Preserves frozen models, validation records, manifests, processed tables, and
fixtures. Does not permanently delete. Does not start downloads.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from vela.settings import DATA_DIR, ROOT

PRESERVE = [
    "data/models",
    "data/processed",
    "data/manifests",
    "data/fixtures",
    "data/catalog",
]
# Order matters: Yakutia first, then Zambia.
CLEANUP_ORDER = ("yakutia", "zambia")
RETRIEVABLE = (
    "Yes — NASA Earthdata via earthaccess (MYD14/MYD03/VNP14IMG/VNP03IMG). "
    "Requires Earthdata login; not in GitHub."
)


def _region_raw(region_id: str) -> Path:
    return DATA_DIR / "raw" / region_id


def _quarantine_root() -> Path:
    return DATA_DIR / "raw" / "_quarantine_pending_delete"


def _classify(name: str) -> str:
    upper = name.upper()
    if upper.startswith(("MYD14", "MOD14", "VNP14", "VJ114", "VJ214")) or "14IMG" in upper:
        return "raw_fire"
    if upper.startswith(("MYD03", "MOD03", "VNP03", "VJ103", "VJ203")) or "03IMG" in upper:
        return "raw_geolocation"
    return "raw_other"


def _basename_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    raw = DATA_DIR / "raw"
    if not raw.exists():
        return index
    for path in raw.rglob("*"):
        if not path.is_file() or "_quarantine" in path.as_posix():
            continue
        region = path.relative_to(raw).parts[0]
        index.setdefault(path.name, []).append(region)
    return index


def build_dry_run(regions: tuple[str, ...] = CLEANUP_ORDER) -> dict:
    index = _basename_index()
    candidates = []
    total = 0
    for region_id in regions:
        root = _region_raw(region_id)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            regions_using = sorted(set(index.get(path.name, [region_id])))
            shared = [item for item in regions_using if item != region_id]
            flags = []
            if shared:
                flags.append("shared_basename")
            if path.suffix.lower() not in {".hdf", ".nc", ".h5", ".nc4"}:
                flags.append("uncertain_extension")
            if _classify(path.name) == "raw_other":
                flags.append("uncertain_product")
            # Known reader regression uses one Yakutia geo file; test skips if absent.
            if "VNP03IMG.A2021326.0248" in path.name:
                flags.append("optional_reader_test_input_skips_if_missing")
            candidates.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "region_id": region_id,
                    "type": _classify(path.name),
                    "bytes": size,
                    "mb": round(size / 1e6, 2),
                    "shared_with_regions": shared,
                    "another_region_uses_it": bool(shared),
                    "retrievable_again": RETRIEVABLE,
                    "preserve": False,
                    "flags": flags,
                    "unique_or_uncertain": bool(flags) or not shared,
                }
            )
    return {
        "mode": "dry_run",
        "order": list(regions),
        "preserve": PRESERVE,
        "candidate_count": len(candidates),
        "total_bytes": total,
        "total_gb": round(total / 1e9, 3),
        "shared_across_regions_count": sum(1 for item in candidates if item["another_region_uses_it"]),
        "candidates": candidates,
        "note": (
            "Processed Zambia/Yakutia parquet tables, frozen models, manifests, "
            "catalog validation records, and fixtures are not on this list."
        ),
    }


def quarantine(regions: tuple[str, ...] = CLEANUP_ORDER) -> dict:
    """Move region raw trees onto the same filesystem for verification."""

    dest_root = _quarantine_root()
    dest_root.mkdir(parents=True, exist_ok=True)
    moved = []
    for region_id in regions:
        source = _region_raw(region_id)
        if not source.exists():
            continue
        target = dest_root / region_id
        if target.exists():
            raise RuntimeError(f"Quarantine target already exists: {target}")
        # Same-filesystem rename; does not free space until permanent delete.
        os.rename(source, target)
        nbytes = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        moved.append(
            {
                "region_id": region_id,
                "from": str(source.relative_to(ROOT)),
                "to": str(target.relative_to(ROOT)),
                "bytes": nbytes,
                "gb": round(nbytes / 1e9, 3),
            }
        )
    return {"mode": "quarantine", "moved": moved, "space_reclaimed": False, "reason": "rename on same volume"}


def restore(regions: tuple[str, ...] = CLEANUP_ORDER) -> dict:
    dest_root = _quarantine_root()
    restored = []
    for region_id in regions:
        source = dest_root / region_id
        target = _region_raw(region_id)
        if not source.exists():
            continue
        if target.exists():
            raise RuntimeError(f"Cannot restore over existing path: {target}")
        os.rename(source, target)
        restored.append({"region_id": region_id, "restored_to": str(target.relative_to(ROOT))})
    if dest_root.exists() and not any(dest_root.iterdir()):
        dest_root.rmdir()
    return {"mode": "restore", "restored": restored}


def verify_app_checks() -> dict:
    from vela.serving import build_calendar, week_cells
    from pathlib import Path
    import json

    cal = build_calendar(25.0, -15.5, 29.0, -12.5, 2021)
    week = next(item for item in cal["weeks"] if item["week_start"] == "2021-07-19")
    rate = week.get("activity_rate")
    denom = week.get("activity_denominator") or week.get("eligible_coverage_cell_days")
    cells = week_cells(25.0, -15.5, 29.0, -12.5, "2021-07-19")
    cell = next(
        (
            item
            for item in cells["contributions"]
            if item.get("cell_id") == "523:-383" and str(item.get("local_date"))[:10] == "2021-07-22"
        ),
        None,
    )
    selection = json.loads((DATA_DIR / "models" / "model_selection.json").read_text(encoding="utf-8"))
    model_path = DATA_DIR / "models" / "vela_model.joblib"
    checks = {
        "zambia_week_activity_percent": None if rate is None else round(float(rate) * 100, 2),
        "zambia_week_cell_days": denom,
        "zambia_week_ok": bool(rate is not None and abs(float(rate) * 100 - 4.77) < 0.01 and int(denom) == 22742),
        "cell_523_383_opens": cell is not None,
        "cell_523_383_probability": None if cell is None else cell.get("model_probability"),
        "cell_523_383_raw_activity": None if cell is None else cell.get("raw_activity"),
        "model_selection_readable": selection.get("chosen_model") == "random_forest",
        "model_selection_mae_pp": (selection.get("weekly_mae_percentage_points") or {}).get("random_forest"),
        "frozen_model_present": model_path.is_file(),
        "yakutia_raw_present": _region_raw("yakutia").exists(),
        "zambia_raw_present": _region_raw("zambia").exists(),
        "downloads_enabled": bool(json.loads((ROOT / "config" / "settings.json").read_text())["downloads_enabled"]),
    }
    checks["all_required_checks_passed"] = all(
        [
            checks["zambia_week_ok"],
            checks["cell_523_383_opens"],
            checks["model_selection_readable"],
            checks["frozen_model_present"],
            checks["downloads_enabled"] is False,
        ]
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--quarantine", action="store_true")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--regions", default="yakutia,zambia")
    args = parser.parse_args()
    regions = tuple(item.strip() for item in args.regions.split(",") if item.strip())
    out_dir = DATA_DIR / "metrics"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.restore:
        report = restore(regions)
        (out_dir / "raw_cleanup_restore.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0

    dry = build_dry_run(regions)
    (out_dir / "raw_cleanup_dry_run.json").write_text(json.dumps(dry, indent=2), encoding="utf-8")
    print(
        f"Dry-run: {dry['candidate_count']} files, {dry['total_gb']} GB. "
        f"Shared across regions: {dry['shared_across_regions_count']}."
    )

    if args.quarantine:
        moved = quarantine(regions)
        (out_dir / "raw_cleanup_quarantine.json").write_text(json.dumps(moved, indent=2), encoding="utf-8")
        print(json.dumps(moved, indent=2))

    if args.verify or args.quarantine:
        checks = verify_app_checks()
        (out_dir / "raw_cleanup_verify.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
        print(json.dumps(checks, indent=2))
        return 0 if checks["all_required_checks_passed"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
