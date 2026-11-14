"""Download and process Maguindanao fire+geo passes into compact coverage cell-days.

Usage:
  python -m scripts.process_mindanao_hotspot_coverage --pilot
  python -m scripts.process_mindanao_hotspot_coverage --batch-aqua --limit-bytes 1500000000
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vela.hotspot_coverage import (
    COVERAGE_PATH,
    HOTSPOT_DAILY_COVERAGE_RULE,
    INVENTORY_PATH,
    PILOT_TRACE_PATH,
    consolidate_daily_coverage,
    freeze_daily_coverage_rule,
    process_fire_geo_pass,
)
from vela.hotspot_forecast import STUDY
from vela.hotspot_forecast_dataset import study_cells
from vela.observation_store import ObservationStore
from vela.pipeline import describe_granule, search_product, try_login
from vela.settings import DATA_DIR, settings

PASS_PATH = DATA_DIR / "processed" / "philippines_hotspot_coverage_passes.parquet"
RAW_ROOT = DATA_DIR / "raw" / "mindanao_hotspot"


def _load_inventory() -> dict:
    if not INVENTORY_PATH.is_file():
        raise SystemExit(f"Missing inventory: {INVENTORY_PATH}. Run inventory_mindanao_hotspot_granules first.")
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _find_granules(fire_name: str, geo_name: str, when_utc: str) -> dict:
    """Re-search CMR for one UTC day and return earthaccess objects by producer id / filename."""

    day = when_utc[:10]
    box = STUDY["bbox"]
    bbox = (box["west"], box["south"], box["east"], box["north"])
    objects = {}
    for short, version in (("MYD14", "061"), ("MYD03", "6.1"), ("VNP14IMG", "002"), ("VNP03IMG", "002")):
        results, _, _ = search_product(short, version, bbox, f"{day}T00:00:00", f"{day}T23:59:59")
        for gran in results:
            item = describe_granule(gran)
            name = item.get("name")
            if name:
                objects[name] = gran
                # MYD03 sometimes listed without .hdf in Identifier
                objects.setdefault(Path(name).name, gran)
                if not name.endswith(".hdf") and short == "MYD03":
                    objects[f"{name}.hdf"] = gran
    return objects


def _download_pair(fire_name: str, geo_name: str, when_utc: str, objects: dict) -> tuple[Path, Path]:
    import earthaccess

    dest = RAW_ROOT / when_utc[:10]
    dest.mkdir(parents=True, exist_ok=True)
    fire_obj = objects.get(fire_name) or objects.get(Path(fire_name).name)
    geo_obj = objects.get(geo_name) or objects.get(Path(geo_name).name)
    if fire_obj is None or geo_obj is None:
        raise SystemExit(f"Could not resolve granules in CMR day search: {fire_name}, {geo_name}")
    saved = earthaccess.download([fire_obj, geo_obj], str(dest))
    paths = [Path(p) for p in saved if p]
    by_name = {p.name: p for p in paths}
    # Also match stems
    fire_path = by_name.get(fire_name) or by_name.get(Path(fire_name).name)
    geo_path = by_name.get(geo_name) or by_name.get(Path(geo_name).name)
    if fire_path is None:
        for p in paths:
            if p.name.startswith("MYD14") or p.name.startswith("VNP14"):
                fire_path = p
    if geo_path is None:
        for p in paths:
            if p.name.startswith("MYD03") or p.name.startswith("VNP03"):
                geo_path = p
    if fire_path is None or geo_path is None:
        raise SystemExit(f"Download incomplete in {dest}: {[p.name for p in paths]}")
    return fire_path, geo_path


def _append_passes(rows: list[dict]) -> None:
    import pandas as pd

    PASS_PATH.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame(rows)
    if PASS_PATH.is_file():
        old = pd.read_parquet(PASS_PATH)
        merged = pd.concat([old, new], ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["cell_id", "ph_date", "platform", "pass_time_utc", "fire_file"], keep="last"
        )
    else:
        merged = new
    merged.to_parquet(PASS_PATH, index=False)
    daily = consolidate_daily_coverage(merged.to_dict(orient="records"))
    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(daily).to_parquet(COVERAGE_PATH, index=False)


def _persist_activity(daily_rows: list[dict]) -> int:
    store = ObservationStore()
    payload = []
    for row in daily_rows:
        payload.append(
            {
                "cell_id": row["cell_id"],
                "ph_date": row["ph_date"],
                "activity_value": 1.0 if row["coverage_status"] == "ok_with_heat" else 0.0,
                "platform": row["platform"],
                "method": "hotspot_fire_mask_coverage_v2_1",
                "coverage_status": "ok" if row["coverage_status"] in {"ok_clear_zero", "ok_with_heat"} else "insufficient",
                "model_version": HOTSPOT_DAILY_COVERAGE_RULE["version"],
                "numerator": float(row.get("qualifying_detection_count") or 0),
                "denominator": 1.0,
                **row,
            }
        )
    return store.upsert_activity_rows(payload)


def run_pilot() -> dict:
    freeze_daily_coverage_rule()
    if not try_login():
        raise SystemExit("Earthdata login required (netrc).")
    inventory = _load_inventory()
    pilot = inventory.get("pilot")
    if not pilot:
        raise SystemExit("No pilot in inventory.")
    free_before = shutil.disk_usage(ROOT).free
    objects = _find_granules(pilot["fire_name"], pilot["geo_name"], pilot["when_utc"])
    fire_path, geo_path = _download_pair(pilot["fire_name"], pilot["geo_name"], pilot["when_utc"], objects)
    when = datetime.fromisoformat(pilot["when_utc"])
    result = process_fire_geo_pass(
        fire_path=fire_path,
        geo_path=geo_path,
        platform=pilot["platform"],
        when=when,
    )
    if not result["ok"]:
        trace = {"pilot": pilot, "process": result, "status": "failed_read"}
        PILOT_TRACE_PATH.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        return trace

    cells = set(study_cells())
    rows = [r for r in result["rows"] if r["cell_id"] in cells]
    _append_passes(rows)
    daily = consolidate_daily_coverage(rows)
    _persist_activity(daily)

    # Pick one clear-zero and one insufficient example without preferring fire outcomes at selection time;
    # now report measured outcomes.
    clear_zeros = [r for r in daily if r["label_support"] == "negative_supported"]
    insufficient = [r for r in daily if r["label_support"] == "unknown"]
    with_heat = [r for r in daily if r["label_support"] == "positive_candidate"]

    example = None
    if clear_zeros:
        example = clear_zeros[0]
        example_kind = "supported_negative"
    elif with_heat:
        example = with_heat[0]
        example_kind = "usable_with_heat"
    elif daily:
        example = daily[0]
        example_kind = daily[0]["label_support"]
    else:
        example_kind = "no_study_cells_touched"

    cloudy = insufficient[0] if insufficient else None

    free_after = shutil.disk_usage(ROOT).free
    trace = {
        "status": "ok",
        "pilot": pilot,
        "daily_coverage_rule": HOTSPOT_DAILY_COVERAGE_RULE,
        "download": {
            "fire_path": str(fire_path),
            "geo_path": str(geo_path),
            "fire_bytes": fire_path.stat().st_size,
            "geo_bytes": geo_path.stat().st_size,
            "free_bytes_before": free_before,
            "free_bytes_after": free_after,
        },
        "pass_summary": {k: v for k, v in result.items() if k != "rows"},
        "study_cells_touched": len(daily),
        "supported_negatives": len(clear_zeros),
        "usable_with_heat": len(with_heat),
        "insufficient_unknown": len(insufficient),
        "traceable_example": None
        if example is None
        else {
            "kind": example_kind,
            "cell_id": example["cell_id"],
            "ph_date": example["ph_date"],
            "platform": example["platform"],
            "pass_time_utc": example["pass_time_utc"],
            "source_granules": {"fire": example["fire_file"], "geo": example["geo_file"]},
            "valid_observed_land_km2": example["visible_land_km2"],
            "valid_observed_land_fraction": example["visible_land_fraction"],
            "qualifying_detection_count": example["qualifying_detection_count"],
            "coverage_status": example["coverage_status"],
            "label_support": example["label_support"],
            "resulting_label": (
                "negative"
                if example["label_support"] == "negative_supported"
                else "positive_candidate"
                if example["label_support"] == "positive_candidate"
                else "unknown"
            ),
        },
        "insufficient_example": None
        if cloudy is None
        else {
            "cell_id": cloudy["cell_id"],
            "ph_date": cloudy["ph_date"],
            "visible_land_km2": cloudy["visible_land_km2"],
            "visible_land_fraction": cloudy["visible_land_fraction"],
            "coverage_status": cloudy["coverage_status"],
            "label_support": "unknown",
            "reason": "visible land < 50% of 25 km² cell (cloud/missing/water/unknown dominate)",
        },
        "coverage_parquet": str(COVERAGE_PATH),
        "passes_parquet": str(PASS_PATH),
        "measured_reason_if_no_negatives": None
        if clear_zeros
        else (
            "Pilot pass touched study cells but none met ≥50% visible land with zero fire pixels"
            if daily
            else "Pilot pass produced no study-cell rows (footprint miss or nighttime filter)"
        ),
    }
    PILOT_TRACE_PATH.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    return trace


def run_batch_aqua(*, limit_bytes: int, max_pairs: int) -> dict:
    freeze_daily_coverage_rule()
    if not try_login():
        raise SystemExit("Earthdata login required (netrc).")
    inventory = _load_inventory()
    free_before = shutil.disk_usage(ROOT).free
    budget = min(limit_bytes, max(0, free_before - 2_000_000_000))  # keep ~2 GB free
    selected = []
    used = 0
    for window in inventory.get("windows") or []:
        for row in window.get("daytime_pairs") or []:
            if row.get("platform") != "Aqua":
                continue
            if row.get("pair_bytes") is None:
                continue
            # skip pilot if already processed — still ok to reprocess
            size = int(row["pair_bytes"])
            if used + size > budget:
                continue
            selected.append(row)
            used += size
            if len(selected) >= max_pairs:
                break
        if len(selected) >= max_pairs:
            break

    cells = set(study_cells())
    processed = []
    all_daily = []
    for row in selected:
        try:
            objects = _find_granules(row["fire_name"], row["geo_name"], row["when_utc"])
            fire_path, geo_path = _download_pair(row["fire_name"], row["geo_name"], row["when_utc"], objects)
            when = datetime.fromisoformat(row["when_utc"])
            result = process_fire_geo_pass(
                fire_path=fire_path, geo_path=geo_path, platform=row["platform"], when=when
            )
            rows = [r for r in (result.get("rows") or []) if r["cell_id"] in cells]
            if rows:
                _append_passes(rows)
                daily = consolidate_daily_coverage(rows)
                _persist_activity(daily)
                all_daily.extend(daily)
            processed.append(
                {
                    "when_utc": row["when_utc"],
                    "ok": result.get("ok"),
                    "reason": result.get("reason"),
                    "study_rows": len(rows),
                    "pair_bytes": row["pair_bytes"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            processed.append({"when_utc": row["when_utc"], "ok": False, "error": str(exc)})

    summary = {
        "status": "batch_aqua_done",
        "selected_pairs": len(selected),
        "budget_bytes": budget,
        "estimated_bytes": used,
        "free_bytes_before": free_before,
        "free_bytes_after": shutil.disk_usage(ROOT).free,
        "processed": processed,
        "coverage_path": str(COVERAGE_PATH),
        "daily_rows_this_batch": len(all_daily),
    }
    out = DATA_DIR / "metrics" / "philippines_hotspot_coverage_batch_aqua.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--batch-aqua", action="store_true")
    parser.add_argument("--limit-bytes", type=int, default=1_500_000_000)
    parser.add_argument("--max-pairs", type=int, default=40)
    args = parser.parse_args()
    if args.pilot:
        print(json.dumps(run_pilot(), indent=2))
        return
    if args.batch_aqua:
        print(json.dumps(run_batch_aqua(limit_bytes=args.limit_bytes, max_pairs=args.max_pairs), indent=2))
        return
    raise SystemExit("Specify --pilot or --batch-aqua")


if __name__ == "__main__":
    main()
