"""Add November to the hotspot-forecast data: NASA FIRMS heat and Aqua fire-mask coverage.

The frozen classifier was trained and evaluated on February, March and August only, so
November squares fall back to a base rate. This collects the same two inputs the existing
pipeline uses, for three past Novembers and the current one, without touching the other
windows (their passes are already processed):

  * FIRMS detections per Philippine day   -> observation store (labels and features)
  * daytime Aqua MYD14 + MYD03 pairs      -> fire-mask coverage cell-days (negatives and
                                             the coverage feature) and burning activity

Each window starts on 25 October so 1 November issues have their seven days of history.
The dataset split (vela.hotspot_forecast_dataset.assign_split) puts November 2023 in
training and November 2024 onwards in the independent test set.

Usage:
  python -m scripts.extend_hotspot_november --firms
  python -m scripts.extend_hotspot_november --inventory
  python -m scripts.extend_hotspot_november --process [--limit-bytes N]
Then retrain and re-audit the fallback:
  python -m scripts.train_hotspot_forecast
  python -m scripts.evaluate_national_prior
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from vela.settings import DATA_DIR  # noqa: E402

NOVEMBER_WINDOWS = [
    ("2023-10-25", "2023-11-30"),
    ("2024-10-25", "2024-11-30"),
    ("2025-10-25", "2025-11-30"),
    ("2026-10-25", "2026-11-14"),
]
INVENTORY = DATA_DIR / "metrics" / "philippines_hotspot_granule_inventory_november.json"
PROGRESS = DATA_DIR / "metrics" / "philippines_hotspot_november_progress.jsonl"


def _days(start: str, end: str) -> list[date]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def _log(entry: dict) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at_utc": datetime.now(timezone.utc).isoformat(), **entry}
    with PROGRESS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    print(json.dumps(entry), flush=True)


def backfill_firms(sleep_seconds: float) -> dict:
    """FIRMS detections for every Philippine day in the windows; resumable by checkpoint."""

    from scripts.backfill_mindanao_firms_hotspot import backfill_day, build_firms
    from vela.boundaries import geometry_from_preset
    from vela.observation_store import ObservationStore

    if not os.environ.get("FIRMS_MAP_KEY", "").strip():
        raise SystemExit("FIRMS_MAP_KEY is required (set it in .env).")
    firms = build_firms()
    store = ObservationStore()
    geometry = geometry_from_preset("mindanao")
    done = skipped = failed = 0
    for start, end in NOVEMBER_WINDOWS:
        for day in _days(start, end):
            checkpoint = store.get_checkpoint(f"hotspot_backfill_{day.isoformat()}")
            if checkpoint and checkpoint.get("regional_query_ok"):
                skipped += 1
                continue
            try:
                row = backfill_day(firms, store, day, geometry)
                done += 1
                _log({"step": "firms", **row})
            except Exception as exc:  # noqa: BLE001 - one bad day must not stop the run
                failed += 1
                _log({"step": "firms", "ph_date": day.isoformat(), "error": f"{type(exc).__name__}: {exc}"[:300]})
            time.sleep(max(0.0, sleep_seconds))
    summary = {"step": "firms_done", "fetched_days": done, "already_done_days": skipped, "failed_days": failed}
    _log(summary)
    return summary


def build_inventory() -> dict:
    """Search NASA CMR for MYD14/MYD03 (and VIIRS) passes over the study box in each window."""

    from scripts.inventory_mindanao_hotspot_granules import inventory_window
    from vela.hotspot_forecast import STUDY
    from vela.pipeline import try_login

    if not try_login():
        raise SystemExit("Earthdata login required (_netrc in your user folder).")
    box = STUDY["bbox"]
    bbox = (box["west"], box["south"], box["east"], box["north"])
    windows = []
    for start, end in NOVEMBER_WINDOWS:
        print(f"Searching {start} .. {end}", flush=True)
        window = inventory_window(start, end, bbox)
        windows.append({key: value for key, value in window.items() if key != "objects_keyed"})
    payload = {"inventoried_at_utc": datetime.now(timezone.utc).isoformat(), "study": STUDY, "windows": windows}
    INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    INVENTORY.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    pairs = [row for window in windows for row in window.get("daytime_pairs") or [] if row.get("platform") == "Aqua"]
    summary = {
        "step": "inventory_done",
        "daytime_aqua_pairs": len(pairs),
        "bytes": sum(int(row.get("pair_bytes") or 0) for row in pairs),
    }
    _log(summary)
    return summary


def process_pairs(limit_bytes: int) -> dict:
    """Download and process each daytime Aqua pair once; resumable (skips processed files)."""

    import pandas as pd

    from scripts.process_mindanao_hotspot_coverage import (
        PASS_PATH,
        _append_passes,
        _download_pair,
        _find_granules,
        _persist_activity,
    )
    from vela.hotspot_coverage import consolidate_daily_coverage, freeze_daily_coverage_rule, process_fire_geo_pass
    from vela.hotspot_forecast_dataset import study_cells
    from vela.pipeline import try_login

    if not INVENTORY.is_file():
        raise SystemExit("Run --inventory first.")
    if not try_login():
        raise SystemExit("Earthdata login required (_netrc in your user folder).")
    freeze_daily_coverage_rule()
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    processed_files = set()
    if PASS_PATH.is_file():
        processed_files = set(pd.read_parquet(PASS_PATH, columns=["fire_file"])["fire_file"].astype(str))
    cells = set(study_cells())
    used = ok = skipped = failed = 0
    # Newest window first: the current month's passes give burning activity for recent days.
    for window in reversed(inventory.get("windows") or []):
        for row in sorted(window.get("daytime_pairs") or [], key=lambda item: item.get("when_utc") or "", reverse=True):
            if row.get("platform") != "Aqua" or row.get("pair_bytes") is None:
                continue
            if any(Path(name).name == Path(row["fire_name"]).name for name in processed_files):
                skipped += 1
                continue
            if used + int(row["pair_bytes"]) > limit_bytes:
                _log({"step": "process_budget_reached", "used_bytes": used})
                return {"step": "process_stopped", "ok": ok, "skipped": skipped, "failed": failed, "used_bytes": used}
            started = time.perf_counter()
            try:
                objects = _find_granules(row["fire_name"], row["geo_name"], row["when_utc"])
                fire_path, geo_path = _download_pair(row["fire_name"], row["geo_name"], row["when_utc"], objects)
                used += int(row["pair_bytes"])
                result = process_fire_geo_pass(
                    fire_path=fire_path,
                    geo_path=geo_path,
                    platform=row["platform"],
                    when=datetime.fromisoformat(row["when_utc"]),
                )
                rows = [item for item in (result.get("rows") or []) if item["cell_id"] in cells]
                if rows:
                    _append_passes(rows)
                    _persist_activity(consolidate_daily_coverage(rows))
                processed_files.add(row["fire_name"])
                ok += 1
                _log({
                    "step": "process",
                    "when_utc": row["when_utc"],
                    "ok": result.get("ok"),
                    "reason": result.get("reason"),
                    "study_rows": len(rows),
                    "seconds": round(time.perf_counter() - started, 1),
                })
            except Exception as exc:  # noqa: BLE001 - one bad pass must not stop the run
                failed += 1
                _log({"step": "process", "when_utc": row.get("when_utc"), "error": f"{type(exc).__name__}: {exc}"[:300]})
    summary = {"step": "process_done", "ok": ok, "already_processed": skipped, "failed": failed, "used_bytes": used}
    _log(summary)
    return summary


EVALUATION = DATA_DIR / "metrics" / "philippines_hotspot_november_evaluation.json"


def evaluate_november() -> dict:
    """Score the selected classifier on November test rows only, against the base rate.

    November 2024 onwards (and odd-x squares) are in the test split, which training,
    model choice and the threshold never see.
    """

    import numpy as np
    import pandas as pd
    from sklearn.metrics import average_precision_score, brier_score_loss, f1_score

    from vela.hotspot_forecast import DATASET_PATH, FEATURE_NAMES, load_selection
    from vela.hotspot_forecast_serve import _load_model_bundle, _predict_probability

    frame = pd.read_parquet(DATASET_PATH)
    frame = frame[frame["label"].notna()].copy()
    frame["month"] = frame["issue_date_ph"].astype(str).str[5:7]
    selection = load_selection() or {}
    bundle = _load_model_bundle(selection)
    if bundle is None:
        raise SystemExit("No usable selected classifier to evaluate.")
    threshold = float(selection.get("threshold") or bundle.get("threshold") or 0.5)
    train = frame[frame["split"] == "train"]
    base_rate = float(train["label"].mean())

    def scores(rows: pd.DataFrame) -> dict:
        labels = rows["label"].astype(int).to_numpy()
        if len(labels) == 0:
            return {"n": 0}
        model_p = np.array([_predict_probability(bundle, row[FEATURE_NAMES].to_dict()) for _, row in rows.iterrows()])
        base_p = np.full(len(labels), base_rate)
        both = len(set(labels)) > 1
        return {
            "n": int(len(labels)),
            "positives": int(labels.sum()),
            "model": {
                "f1": float(f1_score(labels, (model_p >= threshold).astype(int), zero_division=0)),
                "pr_auc": float(average_precision_score(labels, model_p)) if both else None,
                "brier": float(brier_score_loss(labels, model_p)),
                "mean_probability": float(model_p.mean()),
            },
            "base_rate": {
                "probability": base_rate,
                "f1": float(f1_score(labels, (base_p >= threshold).astype(int), zero_division=0)),
                "pr_auc": float(labels.mean()) if both else None,
                "brier": float(brier_score_loss(labels, base_p)),
            },
        }

    test = frame[frame["split"] == "test"]
    november = test[test["month"] == "11"]
    result = {
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": selection.get("chosen_model"),
        "model_hash": selection.get("model_hash"),
        "threshold": threshold,
        "training_rows_by_month": train.groupby("month")["label"].agg(["count", "sum"]).astype(int).to_dict("index"),
        "november_test": scores(november),
        "all_test": scores(test),
        "rule": "November is served by the classifier only if, on November test rows, it beats the base rate "
                "on both Brier score (lower) and PR-AUC (higher).",
    }
    nov = result["november_test"]
    result["november_supported"] = bool(
        nov.get("n")
        and nov["model"]["pr_auc"] is not None
        and nov["model"]["brier"] < nov["base_rate"]["brier"]
        and nov["model"]["pr_auc"] > nov["base_rate"]["pr_auc"]
    )
    EVALUATION.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    _log({"step": "evaluate_done", "november_supported": result["november_supported"], "november_test": nov})
    return result


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--firms", action="store_true", help="backfill FIRMS detections")
    parser.add_argument("--inventory", action="store_true", help="list daytime Aqua passes")
    parser.add_argument("--process", action="store_true", help="download and process passes")
    parser.add_argument("--evaluate", action="store_true", help="score the retrained model on November test rows")
    parser.add_argument("--limit-bytes", type=int, default=12_000_000_000)
    parser.add_argument("--sleep-seconds", type=float, default=0.4)
    args = parser.parse_args()
    if not (args.firms or args.inventory or args.process or args.evaluate):
        parser.error("choose --firms, --inventory, --process and/or --evaluate")
    if args.firms:
        backfill_firms(args.sleep_seconds)
    if args.inventory:
        build_inventory()
    if args.process:
        process_pairs(args.limit_bytes)
    if args.evaluate:
        evaluate_november()


if __name__ == "__main__":
    main()
