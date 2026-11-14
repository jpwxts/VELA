"""Build leakage-safe Mindanao hotspot-forecast cell-day training rows."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from vela.boundaries import geometry_from_preset, point_in_geometry
from vela.firms_day import ph_day_for_utc
from vela.grid import cell_identifier, center, geographic_bounds, indices
from vela.hotspot_forecast import (
    AUDIT_PATH,
    DATASET_PATH,
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    PAIRED_CELLS_PATH,
    SPLIT_PATH,
    STUDY,
    issue_datetime_manila,
)
from vela.hotspot_coverage import COVERAGE_PATH, load_coverage_keys, load_negative_keys
from vela.observation_store import ObservationStore, _connect as store_connect

MANILA_OFFSET = timezone(timedelta(hours=8))
# Vela METHOD: usable when visible land covers ≥ half of the 25 km² cell.
MIN_VISIBLE_LAND_FRACTION = 0.5
# Independent eval reserve: odd x-index cells + dates after the inspected v1 holdout start.
INDEPENDENT_EVAL_DATE_START = date(2024, 8, 1)


def _parse_acq_utc(spot: dict) -> datetime | None:
    acq_date = str(spot.get("acq_date") or "")[:10]
    acq_time = str(spot.get("acq_time") or "00:00")
    if not acq_date:
        return None
    if ":" not in acq_time and str(acq_time).isdigit():
        acq_time = f"{str(acq_time).zfill(4)[:2]}:{str(acq_time).zfill(4)[2:]}"
    try:
        return datetime.fromisoformat(f"{acq_date}T{acq_time}:00").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(f"{acq_date}T{acq_time}").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


_STUDY_CELLS_CACHE: list[str] | None = None
_EVALUATED_CELLS_CACHE: list[str] | None = None


def _cells_for_bbox(box: dict, clip_preset: str) -> list[str]:
    geometry = geometry_from_preset(clip_preset)
    x0, y0 = indices(box["west"], box["south"])
    x1, y1 = indices(box["east"], box["north"])
    cells = []
    for xi in range(min(int(x0), int(x1)), max(int(x0), int(x1)) + 1):
        for yi in range(min(int(y0), int(y1)), max(int(y0), int(y1)) + 1):
            lon, lat = center(xi, yi)
            if not (box["west"] <= lon <= box["east"] and box["south"] <= lat <= box["north"]):
                continue
            if not point_in_geometry(lon, lat, geometry):
                continue
            cells.append(cell_identifier(xi, yi))
    return cells


def study_cells() -> list[str]:
    """All Mindanao land cells in the island study bbox."""

    global _STUDY_CELLS_CACHE
    if _STUDY_CELLS_CACHE is None:
        _STUDY_CELLS_CACHE = _cells_for_bbox(STUDY["bbox"], STUDY["clip_preset"])
    return list(_STUDY_CELLS_CACHE)


def evaluated_cells() -> list[str]:
    """Cells where Maguindanao v2.1 percentage claims are supported."""

    global _EVALUATED_CELLS_CACHE
    if _EVALUATED_CELLS_CACHE is None:
        from vela.hotspot_forecast import MAGUINDANAO_EVALUATED

        _EVALUATED_CELLS_CACHE = _cells_for_bbox(
            MAGUINDANAO_EVALUATED["bbox"], MAGUINDANAO_EVALUATED["clip_preset"]
        )
    return list(_EVALUATED_CELLS_CACHE)


def neighbor_ids(cell_id: str) -> list[str]:
    x_text, y_text = cell_id.split(":", 1)
    x_index, y_index = int(x_text), int(y_text)
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            out.append(cell_identifier(x_index + dx, y_index + dy))
    return out


def firms_regional_query_ok(store: ObservationStore, ph_day: str) -> bool:
    """Successful FIRMS retrieval for the study day — NOT clear-sky coverage."""

    with store_connect(store.path) as connection:
        rows = connection.execute(
            """
            SELECT platform, status FROM feed_checks
            WHERE ph_date = ? AND platform IN ('Aqua','Terra','Suomi-NPP','NOAA-20','NOAA-21')
            """,
            (ph_day,),
        ).fetchall()
    ok = sum(1 for row in rows if row["status"] in {"ok", "ok_zero"})
    return ok >= 2


def fire_mask_coverage_keys(cells: list[str] | None = None) -> dict[str, Any]:
    """Square-days with measured usable fire-mask/geolocation coverage in the study box.

    Primary source: philippines_hotspot_coverage_cell_days.parquet from single-platform
    MYD14/MYD03 or VNP14IMG/VNP03IMG processing. Empty FIRMS searches are excluded.
    """

    cell_set = set(cells or study_cells())
    keys: set[tuple[str, str]] = set()
    negative_keys: set[tuple[str, str]] = set()
    heat_keys: set[tuple[str, str]] = set()
    sources: dict[str, int] = {
        "hotspot_coverage_parquet": 0,
        "activity_cell_days": 0,
        "paired_cells": 0,
    }

    if COVERAGE_PATH.is_file():
        frame = pd.read_parquet(COVERAGE_PATH)
        if len(frame):
            for row in frame.itertuples():
                cid = str(row.cell_id)
                day = str(row.ph_date)[:10]
                if cid not in cell_set:
                    continue
                support = getattr(row, "label_support", None) or ""
                status = getattr(row, "coverage_status", None) or ""
                if support in {"negative_supported", "positive_candidate"} or status in {
                    "ok_clear_zero",
                    "ok_with_heat",
                }:
                    keys.add((cid, day))
                    sources["hotspot_coverage_parquet"] += 1
                if support == "negative_supported" or status == "ok_clear_zero":
                    negative_keys.add((cid, day))
                if support == "positive_candidate" or status == "ok_with_heat":
                    heat_keys.add((cid, day))

    # Also accept keys from the helper loaders (same parquet).
    for key in load_coverage_keys():
        if key[0] in cell_set:
            keys.add(key)
    for key in load_negative_keys():
        if key[0] in cell_set:
            negative_keys.add(key)

    store = ObservationStore()
    with store_connect(store.path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT cell_id, ph_date, coverage_status
                FROM activity_cell_days
                WHERE coverage_status IN ('ok', 'adequate', 'usable')
                """
            ).fetchall()
        except Exception:
            rows = []
    for row in rows:
        if row["cell_id"] in cell_set:
            keys.add((row["cell_id"], str(row["ph_date"])[:10]))
            sources["activity_cell_days"] += 1

    return {
        "square_days": keys,
        "negative_square_days": negative_keys,
        "fire_mask_heat_square_days": heat_keys,
        "count": len(keys),
        "negative_count": len(negative_keys),
        "sources": sources,
        "coverage_parquet": str(COVERAGE_PATH),
        "coverage_parquet_exists": COVERAGE_PATH.is_file(),
        "paired_cells_path": str(PAIRED_CELLS_PATH),
        "paired_cells_exists": PAIRED_CELLS_PATH.is_file(),
        "min_visible_land_fraction": MIN_VISIBLE_LAND_FRACTION,
    }


def load_study_detections(store: ObservationStore) -> list[dict]:
    box = STUDY["bbox"]
    out = []
    with store_connect(store.path) as connection:
        days = [row[0] for row in connection.execute("SELECT DISTINCT ph_date FROM detections").fetchall()]
    for day in days:
        for spot in store.detections_for_ph_date(day):
            try:
                lon = float(spot["lon"])
                lat = float(spot["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (box["west"] <= lon <= box["east"] and box["south"] <= lat <= box["north"]):
                continue
            observed = _parse_acq_utc(spot)
            if observed is None:
                continue
            x_index, y_index = indices(lon, lat)
            cell_id = cell_identifier(int(x_index), int(y_index))
            item = dict(spot)
            item["_acq_utc"] = observed
            item["_cell_id"] = cell_id
            item["acq_date_ph"] = item.get("acq_date_ph") or ph_day_for_utc(
                str(item.get("acq_date") or ""), item.get("acq_time")
            )
            out.append(item)
    return out


def assign_split(issue_date_ph: str, cell_id: str | None = None) -> str:
    """Chronological split with a geographic holdout for independent evaluation.

    Previously inspected v1 holdout (dates ≥ 2024-08-01) stays archived only.
    New independent eval = odd x-index cells OR dates ≥ 2024-08-01.
    Even x-index cells on earlier dates → train / validation by calendar.
    """

    day = date.fromisoformat(issue_date_ph[:10])
    x_index = None
    if cell_id and ":" in cell_id:
        try:
            x_index = int(cell_id.split(":", 1)[0])
        except ValueError:
            x_index = None
    independent = (x_index is not None and x_index % 2 == 1) or day >= INDEPENDENT_EVAL_DATE_START
    if independent:
        return "test"
    if day <= date(2023, 12, 31):
        return "train"
    if day <= date(2024, 3, 31):
        return "validation"
    return "test"


def build_feature_row(
    *,
    cell_id: str,
    issue_date_ph: str,
    detections: list[dict],
    coverage_days: set[str],
    availability_delay_hours: float = 0.0,
) -> dict[str, float | None]:
    """Issue-time features. availability_delay_hours > 0 tests conservative publication lag."""

    issue = issue_datetime_manila(issue_date_ph)
    issue_utc = issue.astimezone(timezone.utc)
    available_before = issue_utc - timedelta(hours=float(availability_delay_hours))
    neighbors = set(neighbor_ids(cell_id))
    d1 = issue_utc - timedelta(days=1)
    d3 = issue_utc - timedelta(days=3)
    d7 = issue_utc - timedelta(days=7)

    heat_1 = heat_3 = heat_7 = 0
    neigh_1 = neigh_3 = 0
    last_det = None
    last_pass = None
    sats_7: set[str] = set()
    for spot in detections:
        observed = spot["_acq_utc"]
        # Conservative: acquisition must also clear the publication delay before issue.
        if observed >= available_before:
            continue
        cid = spot["_cell_id"]
        if cid == cell_id:
            if observed >= d1:
                heat_1 += 1
            if observed >= d3:
                heat_3 += 1
            if observed >= d7:
                heat_7 += 1
                if spot.get("platform"):
                    sats_7.add(str(spot["platform"]))
            last_det = observed if last_det is None or observed > last_det else last_det
        if cid in neighbors:
            if observed >= d1:
                neigh_1 += 1
            if observed >= d3:
                neigh_3 += 1
        if observed >= d7:
            last_pass = observed if last_pass is None or observed > last_pass else last_pass

    cov = 0
    for offset in range(1, 8):
        day = (issue.date() - timedelta(days=offset)).isoformat()
        if day in coverage_days:
            cov += 1

    month = issue.month
    return {
        "heat_detections_1d": float(heat_1),
        "heat_detections_3d": float(heat_3),
        "heat_detections_7d": float(heat_7),
        "neighbor_heat_1d": float(neigh_1),
        "neighbor_heat_3d": float(neigh_3),
        "hours_since_last_detection": None
        if last_det is None
        else (issue_utc - last_det).total_seconds() / 3600.0,
        "hours_since_last_usable_pass": None
        if last_pass is None
        else (issue_utc - last_pass).total_seconds() / 3600.0,
        "coverage_days_7d": float(cov),
        "distinct_satellites_7d": float(len(sats_7)),
        "persistence_heat_yesterday": 1.0 if heat_1 > 0 else 0.0,
        "month_sin": math.sin(2 * math.pi * month / 12.0),
        "month_cos": math.cos(2 * math.pi * month / 12.0),
    }


def publication_delay_sensitivity(
    store: ObservationStore | None = None,
    delays_hours: tuple[float, ...] = (0.0, 6.0, 24.0),
    sample_limit: int = 500,
) -> dict[str, Any]:
    """Measure how often acq≈avail overstates issue-time knowledge vs delayed availability."""

    store = store or ObservationStore()
    cells = study_cells()
    detections = load_study_detections(store)
    by_cell: dict[str, list[dict]] = {}
    for spot in detections:
        by_cell.setdefault(spot["_cell_id"], []).append(spot)
    mask_info = fire_mask_coverage_keys(cells)
    # Fire-mask coverage days for the feature (true usable passes); FIRMS ok days are NOT used.
    coverage_days = {day for (_, day) in mask_info["square_days"]}

    with store_connect(store.path) as connection:
        all_days = sorted(
            row[0] for row in connection.execute("SELECT DISTINCT ph_date FROM feed_checks").fetchall()
        )
    pairs = [(cell, day) for day in all_days for cell in cells]
    rng = np.random.default_rng(0)
    if len(pairs) > sample_limit:
        idx = rng.choice(len(pairs), size=sample_limit, replace=False)
        pairs = [pairs[i] for i in idx]

    base_rows = []
    for cell_id, issue_day in pairs:
        local = list(by_cell.get(cell_id, []))
        for nid in neighbor_ids(cell_id):
            local.extend(by_cell.get(nid, []))
        base = build_feature_row(
            cell_id=cell_id,
            issue_date_ph=issue_day,
            detections=local,
            coverage_days=coverage_days,
            availability_delay_hours=0.0,
        )
        base_rows.append((cell_id, issue_day, local, base))

    out = {"sample_n": len(base_rows), "delays_hours": list(delays_hours), "comparisons": []}
    baseline = [row[3] for row in base_rows]
    for delay in delays_hours:
        if delay == 0.0:
            continue
        changed = 0
        persistence_lost = 0
        heat1_delta = 0.0
        for cell_id, issue_day, local, base in base_rows:
            delayed = build_feature_row(
                cell_id=cell_id,
                issue_date_ph=issue_day,
                detections=local,
                coverage_days=coverage_days,
                availability_delay_hours=delay,
            )
            if any(base[k] != delayed[k] for k in FEATURE_NAMES):
                changed += 1
            if (base["persistence_heat_yesterday"] or 0) > 0 and (
                delayed["persistence_heat_yesterday"] or 0
            ) == 0:
                persistence_lost += 1
            heat1_delta += float(base["heat_detections_1d"] or 0) - float(
                delayed["heat_detections_1d"] or 0
            )
        out["comparisons"].append(
            {
                "delay_hours": delay,
                "fraction_rows_changed": changed / max(1, len(base_rows)),
                "fraction_persistence_lost": persistence_lost / max(1, len(base_rows)),
                "mean_heat_detections_1d_removed": heat1_delta / max(1, len(base_rows)),
                "note": (
                    "Historical replay with this delay better reflects what Vela could have "
                    "known at issue time when FIRMS publication lagged acquisition."
                ),
            }
        )
    out["assumption"] = (
        "Default features use acq≈avail (delay=0). Delay>0 withholds detections whose "
        "acquisition is within the lag window before issue."
    )
    return out


def build_dataset(store: ObservationStore | None = None) -> dict[str, Any]:
    store = store or ObservationStore()
    cells = study_cells()
    detections = load_study_detections(store)
    mask_info = fire_mask_coverage_keys(cells)
    fire_mask_keys = mask_info["square_days"]
    negative_keys = mask_info.get("negative_square_days") or set()
    heat_mask_keys = mask_info.get("fire_mask_heat_square_days") or set()
    # coverage_days_7d feature uses fire-mask days only (not FIRMS empty searches).
    coverage_days = {day for (_, day) in fire_mask_keys}

    with store_connect(store.path) as connection:
        all_days = sorted(
            row[0] for row in connection.execute("SELECT DISTINCT ph_date FROM feed_checks").fetchall()
        )
        firms_ok_days = {day for day in all_days if firms_regional_query_ok(store, day)}

    by_cell: dict[str, list[dict]] = {}
    for spot in detections:
        by_cell.setdefault(spot["_cell_id"], []).append(spot)

    rows = []
    counts = {"positive": 0, "negative": 0, "unknown": 0}
    unknown_reasons = {
        "firms_empty_search_insufficient": 0,
        "no_fire_mask_coverage": 0,
        "firms_query_incomplete": 0,
        "fire_mask_insufficient_land": 0,
    }
    for issue_day in all_days:
        firms_ok = issue_day in firms_ok_days
        issue = issue_datetime_manila(issue_day)
        start = issue.astimezone(timezone.utc)
        end = start + timedelta(days=1)
        for cell_id in cells:
            positives = [
                spot
                for spot in by_cell.get(cell_id, [])
                if start <= spot["_acq_utc"] < end
            ]
            key = (cell_id, issue_day)
            fire_mask_heat = key in heat_mask_keys
            supported_negative = key in negative_keys
            if positives or fire_mask_heat:
                label = 1
                status = "positive"
                counts["positive"] += 1
            elif supported_negative:
                label = 0
                status = "negative"
                counts["negative"] += 1
            else:
                counts["unknown"] += 1
                if not firms_ok:
                    unknown_reasons["firms_query_incomplete"] += 1
                else:
                    unknown_reasons["firms_empty_search_insufficient"] += 1
                if key in fire_mask_keys:
                    unknown_reasons["fire_mask_insufficient_land"] += 1
                else:
                    unknown_reasons["no_fire_mask_coverage"] += 1
                continue

            local = list(by_cell.get(cell_id, []))
            for nid in neighbor_ids(cell_id):
                local.extend(by_cell.get(nid, []))
            features = build_feature_row(
                cell_id=cell_id,
                issue_date_ph=issue_day,
                detections=local,
                coverage_days=coverage_days,
            )
            rows.append(
                {
                    "cell_id": cell_id,
                    "issue_date_ph": issue_day,
                    "label": label,
                    "label_status": status,
                    "split": assign_split(issue_day, cell_id),
                    "recent_heat": int(features["persistence_heat_yesterday"] or 0),
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "coverage_rule_version": "hotspot_coverage_v2_1",
                    **features,
                }
            )

    # Episode leakage guard: contiguous positive cell runs stay in one split bucket.
    positives = [row for row in rows if row["label"] == 1]
    positives.sort(key=lambda r: (r["cell_id"], r["issue_date_ph"]))
    episodes: list[list[dict]] = []
    current: list[dict] = []
    for row in positives:
        if not current:
            current = [row]
            continue
        prev = current[-1]
        if (
            row["cell_id"] == prev["cell_id"]
            and date.fromisoformat(row["issue_date_ph"]) - date.fromisoformat(prev["issue_date_ph"])
            <= timedelta(days=1)
        ):
            current.append(row)
        else:
            episodes.append(current)
            current = [row]
    if current:
        episodes.append(current)
    rank = {"train": 0, "validation": 1, "test": 2}
    for episode in episodes:
        bucket = max((row["split"] for row in episode), key=lambda s: rank[s])
        for row in episode:
            row["split"] = bucket
            row["episode_id"] = f"{row['cell_id']}|{episode[0]['issue_date_ph']}"

    frame = pd.DataFrame(rows)
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(DATASET_PATH, index=False)
    split_counts = (
        frame.groupby("split").size().to_dict() if len(frame) else {"train": 0, "validation": 0, "test": 0}
    )
    total_square_days = len(cells) * len(all_days)
    audit = {
        "audited_commit": "11f1861",
        "coverage_rule_version": "hotspot_coverage_v2",
        "v1_claimed_negatives": 62749,
        "v1_claimed_unknowns": 0,
        "v1_defect": (
            "Negatives were inferred from successful FIRMS searches including empty returns "
            "(ok/ok_zero), not from fire-mask/geolocation usable coverage."
        ),
        "fire_mask_geolocation_square_days": mask_info["count"],
        "fire_mask_sources": mask_info["sources"],
        "firms_regional_ok_days": len(firms_ok_days),
        "firms_ok_is_not_clear_coverage": True,
        "label_counts_v2": counts,
        "unknown_reasons": unknown_reasons,
        "total_square_days_considered": total_square_days,
        "cells": len(cells),
        "feed_check_days": len(all_days),
        "smallest_next_step": (
            "Download and process fire-mask + geolocation pairs (MYD14/MYD03 and "
            "VNP14IMG/VNP03IMG at minimum) for Maguindanao study days; ingest into "
            "paired_cells / activity_cell_days; then rebuild and retrain. "
            "A priori March 2019 quartet alone is ~170 MB (see mindanao_2019-03_download_plan.json); "
            "multi-season coverage for 148 FIRMS days needs a staged disk plan (~12 GB free)."
        ),
        "publication_delay": publication_delay_sensitivity(store),
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(audit, indent=2, default=str) + "\n", encoding="utf-8")

    manifest = {
        "name": "philippines_hotspot_split_v2_1",
        "registered_before_fitting": True,
        "study": STUDY,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "coverage_rule_version": "hotspot_coverage_v2_1",
        "row_counts": {k: int(split_counts.get(k, 0)) for k in ("train", "validation", "test")},
        "label_counts": counts,
        "unknown_reasons": unknown_reasons,
        "fire_mask_coverage_square_days": mask_info["count"],
        "fire_mask_negative_square_days": mask_info.get("negative_count"),
        "firms_regional_ok_days": len(firms_ok_days),
        "cells": len(cells),
        "split_policy": (
            "Even x-index cells with issue date < 2024-08-01 → train (≤2023) / validation (2024-01…03). "
            "Odd x-index cells OR dates ≥ 2024-08-01 → independent test (new geographic+temporal reserve). "
            "Previously inspected v1 holdout remains archived and is not reused as the final claim."
        ),
        "availability_assumption": (
            "Acquisition time treated as availability time by default; "
            "publication-delay sensitivity recorded in philippines_hotspot_coverage_audit.json."
        ),
        "harmonization_holdouts_untouched": True,
        "serving_blocked_until_negatives": counts["negative"] == 0,
        "v1_holdout_archived": True,
    }
    try:
        from vela.settings import ROOT

        manifest["dataset_path"] = str(DATASET_PATH.relative_to(ROOT))
    except Exception:
        manifest["dataset_path"] = str(DATASET_PATH)
    SPLIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "manifest": manifest,
        "audit": audit,
        "rows": len(frame),
        "path": str(DATASET_PATH),
    }
