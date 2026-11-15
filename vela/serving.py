"""Calendar, reveal, and model status for the local app."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from vela.calendar_metrics import CALENDAR_METRIC, missing_rate_dates, summarize_week
from vela.contributions import (
    CONTRIBUTION_RULE,
    METHOD_NAMES,
    apply_chosen_method,
    cell_detail,
    contributions_for_rows,
    tally_activity,
)
from vela.coverage import COVERAGE_RULE
from vela.geo import box_area_deg, in_bbox, intersection_area_deg
from vela.grid import geographic_bounds
from vela.sample import weeks_in_year
from vela.settings import DATA_DIR, WRITABLE_DATA_DIR, regions, settings
from vela.splits import split_for_year

PAIRED_PATH = DATA_DIR / "processed" / "paired_cells.parquet"
EXCLUDED_PATH = DATA_DIR / "processed" / "excluded_cells.parquet"
TRACE_PATH = DATA_DIR / "processed" / "cell_trace.json"
TRACES_PATH = DATA_DIR / "processed" / "cell_traces.json"
MODEL_PATH = DATA_DIR / "models" / "vela_model.joblib"
REPORT_PATH = DATA_DIR / "models" / "report.json"
SELECTION_PATH = DATA_DIR / "models" / "model_selection.json"
JOB_PATH = WRITABLE_DATA_DIR / "jobs" / "status.json"

LABELS = {
    "represented_in_training": "This box mostly overlaps a landscape window used for model development.",
    "reserved_transfer_region": "This box mostly overlaps the reserved landscape. It is kept out of model development and evaluated separately.",
    "not_in_training_sample": "This box does not overlap a sampled training window.",
    "extends_beyond_training_sample": "This box only partly overlaps a sampled window, so it is not treated as one of the training landscapes.",
}


def _read_json(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_job() -> dict | None:
    return _read_json(JOB_PATH)


def write_job(name: str, progress: float, message: str) -> None:
    JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "job": name,
        "progress": max(0.0, min(1.0, float(progress))),
        "message": message,
        "updated": pd.Timestamp.utcnow().isoformat(),
    }
    JOB_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def selected_method() -> str | None:
    selection = _read_json(SELECTION_PATH) or {}
    if selection.get("selection_status") == "selected" and selection.get("chosen_model"):
        return selection["chosen_model"]
    report = _read_json(REPORT_PATH) or {}
    return report.get("chosen_model")


def model_status() -> dict:
    report = _read_json(REPORT_PATH) or {}
    chosen = selected_method()
    ready = bool(chosen) and (chosen == "raw_viirs" or MODEL_PATH.is_file() or (DATA_DIR / "models" / f"candidate_{chosen}.joblib").is_file())
    return {
        "ready": ready,
        "chosen_model": chosen,
        "supported_platform": settings()["supported_platform"],
        "gaps": report.get("gaps") or [],
        "counts": report.get("counts"),
        "validation": report.get("validation"),
        "temporal_test": report.get("temporal_test"),
        "transfer_evaluation": report.get("transfer_evaluation"),
    }


def load_model():
    import joblib

    chosen = selected_method()
    if chosen in {None, "raw_viirs"}:
        return None
    if MODEL_PATH.is_file():
        artifact = joblib.load(MODEL_PATH)
        if artifact.get("model_name") == chosen:
            return artifact
    candidate = DATA_DIR / "models" / f"candidate_{chosen}.joblib"
    if candidate.is_file():
        artifact = joblib.load(candidate)
        return {
            "model_name": chosen,
            "pipeline": artifact["pipeline"],
            "label": "selected",
            "not_final_test": True,
        }
    return None


def _frame(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    return pd.read_parquet(path)


def _filter_box(frame: pd.DataFrame | None, west, south, east, north) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=[] if frame is None else frame.columns)
    mask = in_bbox(frame["center_lon"].to_numpy(), frame["center_lat"].to_numpy(), west, south, east, north)
    return frame.loc[mask].copy()


def _records(frame: pd.DataFrame | None) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return frame.to_dict("records")


def _cell_bounds(cell_id: str | None) -> dict | None:
    if not cell_id or ":" not in str(cell_id):
        return None
    x_text, y_text = str(cell_id).split(":", 1)
    west, south, east, north = geographic_bounds(int(x_text), int(y_text))
    return {"west": west, "south": south, "east": east, "north": north}


def _week_scene(eligible: pd.DataFrame, left_out: pd.DataFrame, artifact=None) -> dict:
    rows = _records(eligible) + _records(left_out)
    scene = contributions_for_rows(rows)
    chosen = selected_method()
    pipeline = None if artifact is None else artifact.get("pipeline")
    scene["contributions"] = apply_chosen_method(scene["contributions"], rows, chosen, pipeline=pipeline)
    scene["chosen_model"] = chosen
    return scene


def _in_week(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if frame.empty or "local_date" not in frame.columns:
        return frame.iloc[0:0]
    days = frame["local_date"].astype(str).str.slice(0, 10)
    return frame[(days >= start.isoformat()) & (days <= end.isoformat())]


def region_label(west: float, south: float, east: float, north: float) -> dict:
    user = (float(west), float(south), float(east), float(north))
    area = box_area_deg(*user)
    best_fraction = 0.0
    best = None
    for region in regions():
        box = (region["west"], region["south"], region["east"], region["north"])
        overlap = intersection_area_deg(user, box)
        fraction = overlap / area if area else 0.0
        if fraction > best_fraction:
            best_fraction = fraction
            best = region
    if best is None or best_fraction <= 0:
        code = "not_in_training_sample"
    elif best_fraction < 0.5:
        code = "extends_beyond_training_sample"
    elif best["role"] == "transfer":
        code = "reserved_transfer_region"
    else:
        code = "represented_in_training"
    text = LABELS[code]
    if best is not None and code == "reserved_transfer_region":
        text = (
            f"This box mostly overlaps the reserved {best['name']} window. "
            "It is kept out of model development and evaluated separately."
        )
    if best is not None and code == "represented_in_training":
        text = (
            f"This box mostly overlaps the {best['name']} window used for model development."
        )
    return {
        "code": code,
        "text": text,
        "region_id": None if best is None else best["id"],
        "overlap_fraction": round(best_fraction, 3),
    }


def _held_out(iso_year: int, label: dict) -> bool:
    if label["code"] in {"reserved_transfer_region", "not_in_training_sample"}:
        return True
    return split_for_year(iso_year) == "test"


def _estimate(frame: pd.DataFrame, artifact) -> float | None:
    if frame.empty or artifact is None:
        return None
    from vela.train import _prepare, _probabilities

    prepared = _prepare(frame, settings())
    probability = _probabilities(artifact["model_name"], artifact["pipeline"], prepared)
    if len(probability) == 0:
        return None
    return float(probability.mean())


def list_calendar_years(west: float, south: float, east: float, north: float) -> dict:
    """Years that have at least one published weekly estimate for this land box."""

    import pandas as pd

    label = region_label(west, south, east, north)
    paired = _filter_box(_frame(PAIRED_PATH), west, south, east, north)
    excluded = _filter_box(_frame(EXCLUDED_PATH), west, south, east, north)
    if (paired is None or paired.empty) and (excluded is None or excluded.empty):
        return {
            "status": "not_processed",
            "region": label,
            "years": [],
            "observation_years": [],
        }
    frames = []
    if paired is not None and not paired.empty:
        frames.append(paired)
    if excluded is not None and not excluded.empty:
        frames.append(excluded)
    dates = pd.concat(frames, ignore_index=True)["local_date"]
    observation_years = sorted({int(value) for value in pd.to_datetime(dates).dt.year.tolist()})
    years = []
    for year in observation_years:
        payload = build_calendar(west, south, east, north, year)
        published = [
            week
            for week in payload.get("weeks") or []
            if week.get("activity_status") in {"complete", "partial"}
        ]
        if published:
            years.append({"year": year, "week_count": len(published)})
    return {
        "status": "ok",
        "region": label,
        "years": years,
        "observation_years": observation_years,
    }


def build_calendar(west: float, south: float, east: float, north: float, year: int) -> dict:
    label = region_label(west, south, east, north)
    status = model_status()
    artifact = load_model() if status["ready"] else None
    paired = _filter_box(_frame(PAIRED_PATH), west, south, east, north)
    excluded = _filter_box(_frame(EXCLUDED_PATH), west, south, east, north)
    base = {
        "metric": CALENDAR_METRIC,
        "coverage_rule": COVERAGE_RULE,
        "region": label,
        "model": {
            "ready": status["ready"],
            "chosen_model": status["chosen_model"],
            "supported_platform": status["supported_platform"],
            "gaps": status["gaps"],
        },
        "platform_note": (
            "Each adequately observed cell-day is counted once. Aqua supplies it when coverage is eligible; "
            "otherwise one VIIRS platform is selected by coverage and time, not by hotspot count. "
            "NOAA-20 and NOAA-21 raw observations stay on the map. Their harmonized estimates are calibration pending."
        ),
        "progress": read_job(),
        "year": year,
    }
    if _frame(PAIRED_PATH) is None and _frame(EXCLUDED_PATH) is None:
        return {**base, "status": "not_processed", "weeks": []}
    if paired.empty and excluded.empty:
        return {**base, "status": "not_processed", "weeks": []}

    weeks = []
    for monday, sunday, thursday in weeks_in_year(year):
        eligible = _in_week(paired, monday, sunday)
        left_out = _in_week(excluded, monday, sunday)
        if eligible.empty and left_out.empty:
            weeks.append(
                {
                    "week_start": monday.isoformat(),
                    "week_end": sunday.isoformat(),
                    "coverage_status": "not_processed",
                    "held_out": _held_out(thursday.year, label),
                    "split": split_for_year(thursday.year),
                    "usable_cell_days": 0,
                    "eligible_coverage_cell_days": 0,
                    "activity_estimate_cell_days": 0,
                    "activity_denominator": None,
                    "activity_rate": None,
                    "activity_status": "unavailable",
                    "method_counts": {name: 0 for name in METHOD_NAMES},
                    "days_observed": 0,
                    "mean_shared_coverage": None,
                    "viirs_rate": None,
                    "estimated_rate": None,
                    "observed_rate": None,
                    "observed_available": False,
                    "reveal_enabled": False,
                    "clear_zero": False,
                }
            )
            continue
        records = _records(eligible)
        scene = _week_scene(eligible, left_out, artifact=artifact)
        summary = summarize_week(records, settings())
        tally = tally_activity(scene["contributions"])
        eligible_days = set(eligible["local_date"].astype(str).str.slice(0, 10)) if not eligible.empty else set()
        excluded_days = set(left_out["local_date"].astype(str).str.slice(0, 10)) if not left_out.empty else set()
        held = _held_out(thursday.year, label)
        established = bool(tally["coverage_established"])
        activity_status = "hidden" if held else ("unavailable" if not established else tally["activity_status"])
        activity_rate = None if held or not established else tally["activity_rate"]
        sufficient = summary["coverage_status"] == "ok"
        estimated = _estimate(pd.DataFrame(records), artifact) if sufficient and records else None
        observed_available = sufficient and summary["observed_rate"] is not None
        reveal_enabled = bool(held and sufficient and status["ready"] and observed_available and estimated is not None)
        weeks.append(
            {
                "week_start": monday.isoformat(),
                "week_end": sunday.isoformat(),
                "coverage_status": "ok" if established else "insufficient",
                "held_out": held,
                "split": split_for_year(thursday.year),
                "usable_cell_days": summary["usable_cell_days"],
                "eligible_coverage_cell_days": tally["eligible_coverage_cell_days"],
                "activity_estimate_cell_days": tally["activity_estimate_cell_days"],
                "activity_denominator": None if held or not established else tally["activity_denominator"],
                "activity_rate": activity_rate,
                "activity_status": activity_status,
                "method_counts": tally["method_counts"],
                "days_observed": summary["days_observed"],
                "mean_shared_coverage": summary["mean_shared_coverage"],
                "mean_supplying_coverage": tally["mean_supplying_coverage"],
                "viirs_rate": summary["viirs_rate"],
                "contribution_rate": activity_rate,
                "contribution_cell_days": tally["eligible_coverage_cell_days"],
                "contribution_rule": CONTRIBUTION_RULE,
                "harmonized_noaa": "calibration pending",
                "estimated_rate": estimated,
                "observed_rate": None if held else summary["observed_rate"],
                "observed_available": observed_available,
                "reveal_enabled": reveal_enabled,
                "clear_zero": bool(tally["clear_zero"] and not held),
                "viirs_clear": bool(sufficient and summary["viirs_active_cell_days"] == 0),
                "insufficient_dates": missing_rate_dates(eligible_days, excluded_days),
            }
        )
    return {**base, "status": "ok", "weeks": weeks}


def week_cells(west: float, south: float, east: float, north: float, week_start: str) -> dict:
    """Cell-day contributions for one week. Held-out Aqua detections stay hidden."""

    monday = date.fromisoformat(week_start)
    sunday = date.fromordinal(monday.toordinal() + 6)
    thursday = date.fromordinal(monday.toordinal() + 3)
    label = region_label(west, south, east, north)
    paired = _in_week(_filter_box(_frame(PAIRED_PATH), west, south, east, north), monday, sunday)
    excluded = _in_week(_filter_box(_frame(EXCLUDED_PATH), west, south, east, north), monday, sunday)
    artifact = load_model() if model_status()["ready"] else None
    scene = _week_scene(paired, excluded, artifact=artifact)
    held = _held_out(thursday.year, label)
    tally = tally_activity(scene["contributions"])
    details = []
    ordered = sorted(
        scene["contributions"],
        key=lambda item: (
            0 if item.get("rule") == "viirs_coverage_and_time" else 1,
            str(item.get("local_date") or ""),
            str(item.get("cell_id") or ""),
        ),
    )
    for item in ordered:
        enriched = dict(item)
        enriched["bounds"] = _cell_bounds(item.get("cell_id"))
        details.append(cell_detail(enriched, held_out=held))
    return {
        "week_start": week_start,
        "week_end": sunday.isoformat(),
        "held_out": held,
        "rule": CONTRIBUTION_RULE,
        "chosen_model": scene.get("chosen_model"),
        "cell_days": scene["cell_days"],
        "eligible_coverage_cell_days": tally["eligible_coverage_cell_days"],
        "activity_estimate_cell_days": tally["activity_estimate_cell_days"],
        "activity_denominator": tally["activity_denominator"],
        "activity_rate": None if held else tally["activity_rate"],
        "activity_status": "hidden" if held else tally["activity_status"],
        "method_counts": tally["method_counts"],
        "clear_zero": bool(tally["clear_zero"] and not held),
        "harmonized_noaa": "calibration pending",
        "contributions": details,
    }


def reveal_week(west: float, south: float, east: float, north: float, week_start: str) -> dict:
    monday = date.fromisoformat(week_start)
    sunday = date.fromordinal(monday.toordinal() + 6)
    payload = build_calendar(west, south, east, north, monday.year)
    match = next((week for week in payload["weeks"] if week["week_start"] == week_start), None)
    if match is None:
        return {"ok": False, "reason": "That week is not in the calendar."}
    if not match["reveal_enabled"] and not (
        match["held_out"] and match["coverage_status"] == "ok" and match["observed_available"]
    ):
        reason = "Reveal stays off until a trained model and usable held-out observations both exist."
        if payload["model"]["gaps"]:
            reason = payload["model"]["gaps"][0]
        return {"ok": False, "reason": reason, "week": match}
    paired = _in_week(_filter_box(_frame(PAIRED_PATH), west, south, east, north), monday, sunday)
    summary = summarize_week(paired.to_dict("records"), settings())
    observed = summary["observed_rate"]
    estimated = match["estimated_rate"]
    if estimated is None and model_status()["ready"]:
        estimated = _estimate(paired, load_model())
    if observed is None or estimated is None:
        return {"ok": False, "reason": "Observed MODIS and the estimate are not both available for this week."}
    return {
        "ok": True,
        "week_start": week_start,
        "week_end": sunday.isoformat(),
        "viirs_rate": summary["viirs_rate"],
        "estimated_rate": estimated,
        "observed_rate": observed,
        "difference_percentage_points": (estimated - observed) * 100.0,
        "usable_cell_days": summary["usable_cell_days"],
        "days_observed": summary["days_observed"],
        "mean_shared_coverage": summary["mean_shared_coverage"],
        "coverage_status": summary["coverage_status"],
        "metric": CALENDAR_METRIC,
    }


def calendar_rows(payload: dict, include_observed: bool) -> list[dict]:
    rows = []
    for week in payload.get("weeks", []):
        observed = week.get("observed_rate")
        if week.get("held_out") and not include_observed:
            observed = None
        rows.append(
            {
                "week_start": week.get("week_start"),
                "week_end": week.get("week_end"),
                "split": week.get("split"),
                "held_out": week.get("held_out"),
                "coverage_status": week.get("coverage_status"),
                "usable_cell_days": week.get("usable_cell_days"),
                "eligible_coverage_cell_days": week.get("eligible_coverage_cell_days"),
                "activity_estimate_cell_days": week.get("activity_estimate_cell_days"),
                "activity_denominator": week.get("activity_denominator"),
                "activity_status": week.get("activity_status"),
                "observed_aqua_activity_cell_days": (week.get("method_counts") or {}).get("observed Aqua activity"),
                "raw_viirs_activity_cell_days": (week.get("method_counts") or {}).get("raw VIIRS activity"),
                "calibrated_viirs_estimate_cell_days": (week.get("method_counts") or {}).get("calibrated VIIRS estimate"),
                "unavailable_activity_cell_days": (week.get("method_counts") or {}).get("unavailable"),
                "activity_share_of_estimated_cell_days": week.get("activity_rate"),
                "days_observed": week.get("days_observed"),
                "mean_shared_coverage": week.get("mean_shared_coverage"),
                "viirs_share_of_usable_cell_days": week.get("viirs_rate"),
                "estimated_modis_share_of_usable_cell_days": week.get("estimated_rate"),
                "observed_modis_share_of_usable_cell_days": observed,
            }
        )
    return rows
