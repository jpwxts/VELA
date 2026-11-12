"""Compare the three activity estimates and keep the final test untouched until selection."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from vela.calendar_metrics import summarize_week
from vela.features import FEATURE_COLUMNS, feature_values, viirs_counts_from_mapping
from vela.geo import season_of
from vela.settings import data_dir, settings
from vela.splits import split_for_year

MODEL_ORDER = ("raw_viirs", "logistic_regression", "random_forest")
MODEL_PATH = "vela_model.joblib"
REPORT_PATH = "report.json"


def supported_platform_rows(frame: pd.DataFrame, config: dict | None = None) -> pd.DataFrame:
    """Keep the frozen Suomi-NPP table when other VIIRS platforms are stored beside it."""

    platform = (config or settings())["supported_platform"]
    if frame.empty or "viirs_platform" not in frame.columns:
        return frame
    mask = frame["viirs_platform"].isna() | (frame["viirs_platform"].astype(str) == platform)
    return frame.loc[mask].copy()


def _prepare(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    work = frame.copy()
    work["local_date"] = pd.to_datetime(work["local_date"])
    iso = work["local_date"].dt.isocalendar()
    work["iso_year"] = iso.year.astype(int)
    work["iso_week"] = iso.week.astype(int)
    work["split"] = work["iso_year"].map(lambda year: split_for_year(int(year), config))
    features = [
        feature_values(
            viirs_counts_from_mapping(row._asdict()),
            row.center_lat,
            row.center_lon,
            row.local_date,
            row.local_hour,
            config,
        )
        for row in work.itertuples(index=False)
    ]
    feature_frame = pd.DataFrame(features, index=work.index)
    for column in FEATURE_COLUMNS:
        work[column] = feature_frame[column].to_numpy()
    return work


def _weeks(frame: pd.DataFrame, probability: np.ndarray, config: dict) -> list[dict]:
    work = frame.copy()
    work["probability"] = probability
    rows = []
    if work.empty:
        return rows
    for (region_id, iso_year, iso_week), part in work.groupby(["region_id", "iso_year", "iso_week"], sort=True):
        records = part.to_dict("records")
        summary = summarize_week(records, config)
        thursday = date.fromisocalendar(int(iso_year), int(iso_week), 4)
        predicted = float(part["probability"].mean())
        rows.append(
            {
                "region_id": region_id,
                "iso_year": int(iso_year),
                "iso_week": int(iso_week),
                "week_start": (thursday - timedelta(days=3)).isoformat(),
                "season": season_of(thursday.month),
                "coverage_status": summary["coverage_status"],
                "usable_cell_days": summary["usable_cell_days"],
                "mean_shared_coverage": summary["mean_shared_coverage"],
                "observed_rate": summary["observed_rate"],
                "predicted_rate": predicted if summary["coverage_status"] == "ok" else None,
            }
        )
    return rows


def _fit_thresholds(weeks: list[dict], config: dict) -> dict[str, float | None]:
    grouped: dict[str, list[float]] = {}
    for week in weeks:
        if week["coverage_status"] != "ok" or week["observed_rate"] is None:
            continue
        grouped.setdefault(f"{week['region_id']}|{week['season']}", []).append(float(week["observed_rate"]))
    thresholds = {}
    minimum = int(config["min_weeks_for_threshold"])
    quantile = float(config["unusual_quantile"])
    for key, values in grouped.items():
        if len(values) < minimum:
            thresholds[key] = None
        else:
            thresholds[key] = float(np.quantile(values, quantile))
    return thresholds


def _score(weeks: list[dict], thresholds: dict[str, float | None]) -> dict:
    usable = [week for week in weeks if week["coverage_status"] == "ok" and week["predicted_rate"] is not None]
    insufficient = len(weeks) - len(usable)
    if not usable:
        mae = None
    else:
        mae = float(np.mean([abs(week["predicted_rate"] - week["observed_rate"]) * 100 for week in usable]))
    missed = extra = compared = missing_threshold = 0
    for week in usable:
        threshold = thresholds.get(f"{week['region_id']}|{week['season']}")
        if threshold is None:
            missing_threshold += 1
            continue
        compared += 1
        observed_unusual = week["observed_rate"] >= threshold
        predicted_unusual = week["predicted_rate"] >= threshold
        if observed_unusual and not predicted_unusual:
            missed += 1
        if predicted_unusual and not observed_unusual:
            extra += 1
    return {
        "weeks": len(weeks),
        "weeks_with_sufficient_coverage": len(usable),
        "weeks_with_insufficient_coverage": insufficient,
        "insufficient_coverage_share": (insufficient / len(weeks)) if weeks else None,
        "weekly_mae_percentage_points": mae,
        "unusual_weeks_compared": compared,
        "unusual_weeks_missed": missed,
        "extra_weeks_flagged": extra,
        "weeks_without_seasonal_threshold": missing_threshold,
    }


def _probabilities(name: str, pipeline, frame: pd.DataFrame) -> np.ndarray:
    if name == "raw_viirs":
        return (frame["viirs_hotspot_pixels"].to_numpy(dtype=float) >= 1.0).astype(float)
    return pipeline.predict_proba(frame.loc[:, list(FEATURE_COLUMNS)])[:, 1]


def _fit(frame: pd.DataFrame, config: dict) -> dict:
    predictors = frame.loc[:, list(FEATURE_COLUMNS)]
    target = frame["modis_detected"].astype(int)
    logistic = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=800, class_weight="balanced")),
        ]
    )
    forest = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=200,
                    min_samples_leaf=5,
                    class_weight="balanced_subsample",
                    random_state=int(config["seed"]),
                    n_jobs=1,
                ),
            ),
        ]
    )
    logistic.fit(predictors, target)
    forest.fit(predictors, target)
    return {"logistic_regression": logistic, "random_forest": forest, "raw_viirs": None}


CANDIDATE_FILES = {
    "logistic_regression": "candidate_logistic_regression.joblib",
    "random_forest": "candidate_random_forest.joblib",
}
CANDIDATE_REPORT = "candidate_report.json"


def training_data_status(frame: pd.DataFrame, config: dict) -> dict:
    """Checks on the 2013–2020 development rows. Validation weeks are not part of this check."""

    prepared = _prepare(frame, config)
    development = prepared[prepared["role"] == "train"]
    train = development[development["split"] == "train"]
    positives = int(train["modis_detected"].astype(bool).sum()) if len(train) else 0
    train_years = sorted(set(train["iso_year"].tolist())) if len(train) else []
    train_regions = sorted(set(train["region_id"].tolist())) if len(train) else []
    gaps = []
    if positives < int(config["min_train_positives"]):
        gaps.append(
            f"Training positives are {positives}; at least {config['min_train_positives']} are required."
        )
    if len(train_years) < int(config["min_train_years"]):
        gaps.append(
            f"Training years present: {train_years or 'none'}; at least {config['min_train_years']} are required."
        )
    if len(train_regions) < int(config["min_train_regions"]):
        gaps.append(
            f"Training regions present: {train_regions or 'none'}; at least {config['min_train_regions']} are required."
        )
    return {
        "prepared": prepared,
        "train": train,
        "gaps": gaps,
        "counts": {
            "train_rows": int(len(train)),
            "tune_rows": int((development["split"] == "tune").sum()),
            "test_rows": int((development["split"] == "test").sum()),
            "transfer_rows": int((prepared["role"] == "transfer").sum()),
            "train_positives": positives,
            "train_years": train_years,
            "train_regions": train_regions,
        },
    }


def fit_candidates(table_path: Path, config: dict | None = None) -> dict:
    """Fit the two candidate models on 2013–2020 rows. This does not choose a model."""

    cfg = config or settings()
    report = {
        "label": "candidate",
        "purpose": "Candidates for later 2021–2022 comparison. Not Reveal MODIS and not the final model.",
        "not_for_reveal": True,
        "not_the_final_model": True,
        "chosen_model": None,
        "validation": "pending",
        "temporal_test": None,
        "transfer_evaluation": None,
        "feature_columns": list(FEATURE_COLUMNS),
        "class_weight": {
            "logistic_regression": "balanced",
            "random_forest": "balanced_subsample",
        },
        "gaps": [],
        "model_files": {},
    }
    if not table_path.is_file():
        report["gaps"].append(f"No paired-cell table at {table_path}.")
        _write_candidate_report(report)
        return report
    frame = supported_platform_rows(pd.read_parquet(table_path), cfg)
    if frame.empty or "data_origin" not in frame.columns or not bool((frame["data_origin"] == "nasa").all()):
        report["gaps"].append("Candidate fitting refused because the table is empty or is not marked as NASA observations.")
        _write_candidate_report(report)
        _clear_candidates()
        return report
    status = training_data_status(frame, cfg)
    report["counts"] = status["counts"]
    report["gaps"] = status["gaps"]
    if status["gaps"]:
        report["validation"] = "pending"
        _write_candidate_report(report)
        _clear_candidates()
        return report
    fitted = _fit(status["train"], cfg)
    folder = data_dir("models")
    for name, filename in CANDIDATE_FILES.items():
        pipeline = fitted[name]
        probabilities = pipeline.predict_proba(status["train"].loc[:, list(FEATURE_COLUMNS)])[:, 1]
        if not np.all((probabilities >= 0.0) & (probabilities <= 1.0)):
            raise RuntimeError(f"{name} produced a probability outside 0 to 1.")
        artifact = {
            "label": "candidate",
            "model_name": name,
            "pipeline": pipeline,
            "feature_columns": list(FEATURE_COLUMNS),
            "not_for_reveal": True,
            "not_the_final_model": True,
            "training_rows": status["counts"]["train_rows"],
            "training_positives": status["counts"]["train_positives"],
            "training_years": status["counts"]["train_years"],
            "training_regions": status["counts"]["train_regions"],
            "seed": int(cfg["seed"]),
            "supported_platform": cfg["supported_platform"],
            "class_weight": report["class_weight"][name],
        }
        path = folder / filename
        joblib.dump(artifact, path)
        reloaded = joblib.load(path)
        checked = reloaded["pipeline"].predict_proba(status["train"].loc[:, list(FEATURE_COLUMNS)])[:, 1]
        if not np.all((checked >= 0.0) & (checked <= 1.0)):
            raise RuntimeError(f"Reloaded {name} produced a probability outside 0 to 1.")
        report["model_files"][name] = str(path)
        report[f"{name}_probability_span"] = [float(checked.min()), float(checked.max())]
    report["validation"] = "pending" if status["counts"]["tune_rows"] == 0 else "not_scored_by_this_step"
    _write_candidate_report(report)
    return report


SELECTION_REPORT = "model_selection.json"


def candidate_identifiers(folder: Path | None = None) -> dict:
    """Identifiers for the saved candidate files. Loading them does not refit them."""

    directory = folder or data_dir("models")
    found = {}
    for name, filename in CANDIDATE_FILES.items():
        path = directory / filename
        if not path.is_file():
            found[name] = {"file": filename, "exists": False, "sha256": None}
            continue
        artifact = joblib.load(path)
        found[name] = {
            "file": filename,
            "exists": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "label": artifact.get("label"),
            "training_rows": artifact.get("training_rows"),
            "training_regions": artifact.get("training_regions"),
            "training_years": artifact.get("training_years"),
        }
    return found


def selection_frame(prepared: pd.DataFrame) -> pd.DataFrame:
    """2021–2022 development rows only. The final test and Pantanal stay out."""

    tune = prepared[(prepared["role"] == "train") & (prepared["split"] == "tune")].copy()
    if len(tune) and bool((tune["iso_year"] >= 2023).any()):
        raise RuntimeError("Model selection received a year reserved for the final test.")
    if len(tune) and bool((tune["region_id"] == "pantanal").any()):
        raise RuntimeError("Pantanal entered model selection.")
    return tune


def _selection_rows(tune: pd.DataFrame, pipelines: dict, config: dict, trained_regions: set[str]) -> list[dict]:
    if tune.empty:
        return []
    grouped = {}
    for name in MODEL_ORDER:
        weeks = _weeks(tune, _probabilities(name, pipelines[name], tune), config)
        grouped[name] = {(week["region_id"], week["week_start"]): week for week in weeks}
    days = tune.copy()
    days["day"] = days["local_date"].dt.strftime("%Y-%m-%d")
    day_counts = {
        (region_id, int(year), int(week)): int(count)
        for (region_id, year, week), count in days.groupby(["region_id", "iso_year", "iso_week"])["day"].nunique().items()
    }
    rows = []
    for key, base in grouped["raw_viirs"].items():
        scored = base["coverage_status"] == "ok" and base["observed_rate"] is not None
        estimates = {}
        errors = {}
        for name in MODEL_ORDER:
            predicted = grouped[name][key]["predicted_rate"]
            estimates[name] = predicted if scored else None
            errors[name] = abs(predicted - base["observed_rate"]) * 100 if scored else None
        rows.append(
            {
                "region_id": base["region_id"],
                "region_group": "previously_trained" if base["region_id"] in trained_regions else "new",
                "week_start": base["week_start"],
                "season": base["season"],
                "iso_year": base["iso_year"],
                "usable_days": day_counts.get((base["region_id"], base["iso_year"], base["iso_week"]), 0),
                "usable_cell_days": base["usable_cell_days"],
                "coverage_status": base["coverage_status"],
                "scored": scored,
                "observed_modis_rate": base["observed_rate"] if scored else None,
                "estimates": estimates,
                "absolute_error_percentage_points": errors,
            }
        )
    return rows


def _equal_week_mae(rows: list[dict]) -> dict[str, float | None]:
    scored = [row for row in rows if row["scored"]]
    if not scored:
        return {name: None for name in MODEL_ORDER}
    return {
        name: float(np.mean([row["absolute_error_percentage_points"][name] for row in scored]))
        for name in MODEL_ORDER
    }


def score_frozen_pipelines(
    prepared: pd.DataFrame,
    pipelines: dict,
    trained_regions: list[str],
    config: dict | None = None,
) -> dict:
    """Score saved pipelines on identical 2021–2022 cell-days. This does not fit or save a model."""

    cfg = config or settings()
    trained = set(trained_regions)
    rows = _selection_rows(selection_frame(prepared), pipelines, cfg, trained)
    scored = [row for row in rows if row["scored"]]
    mae = _equal_week_mae(rows)
    grouped = {
        "previously_trained": _equal_week_mae([row for row in rows if row["region_group"] == "previously_trained"]),
        "new": _equal_week_mae([row for row in rows if row["region_group"] == "new"]),
    }
    minimum = int(cfg["min_tune_weeks"])
    enough = len(scored) >= minimum
    chosen = None
    if enough:
        chosen = sorted(MODEL_ORDER, key=lambda name: (mae[name], MODEL_ORDER.index(name)))[0]
    return {
        "label": "model selection",
        "weeks": rows,
        "scored_weeks": len(scored),
        "unscored_weeks": len(rows) - len(scored),
        "minimum_scored_weeks": minimum,
        "enough_weeks_to_select": enough,
        "weekly_mae_percentage_points": mae,
        "weekly_mae_by_region_group": grouped,
        "chosen_model": chosen,
        "selection_status": "selected" if enough else "preliminary",
        "final_test_evaluated": False,
        "temporal_test": None,
        "transfer_evaluation": None,
        "tie_break": "Lower weekly mean absolute error wins. Each scored region-week has equal weight. Ties prefer raw VIIRS, then logistic regression, then random forest.",
    }


def run_model_selection(table_path: Path, config: dict | None = None) -> dict:
    """Score the frozen candidate files. The reserved final test is not evaluated."""

    cfg = config or settings()
    before = candidate_identifiers()
    model_file = data_dir("models") / MODEL_PATH
    model_existed = model_file.exists()
    report = {
        "label": "model selection",
        "purpose": "Choose among frozen candidates using 2021–2022 weeks. The 2023–2024 final test stays reserved for Reveal MODIS.",
        "candidate_identifiers": before,
        "chosen_model": None,
        "selection_status": "preliminary",
        "final_test_evaluated": False,
        "temporal_test": None,
        "reveal_performance": "pending_until_final_test",
    }
    missing = [name for name, item in before.items() if not item["exists"]]
    if missing or not table_path.is_file():
        report["gaps"] = ["Both frozen candidate files and the paired-cell table are required."]
        _write_selection(report)
        return report
    frame = supported_platform_rows(pd.read_parquet(table_path), cfg)
    if frame.empty or "data_origin" not in frame.columns or not bool((frame["data_origin"] == "nasa").all()):
        report["gaps"] = ["Model selection refused because the table is empty or is not marked as NASA observations."]
        _write_selection(report)
        return report
    prepared = _prepare(frame, cfg)
    trained = before["logistic_regression"].get("training_regions") or []
    folder = data_dir("models")
    pipelines = {"raw_viirs": None}
    for name in ("logistic_regression", "random_forest"):
        pipelines[name] = joblib.load(folder / CANDIDATE_FILES[name])["pipeline"]
    scored = score_frozen_pipelines(prepared, pipelines, trained, cfg)
    after = candidate_identifiers()
    if {name: item["sha256"] for name, item in before.items()} != {name: item["sha256"] for name, item in after.items()}:
        raise RuntimeError("A candidate file changed during model selection.")
    report.update(scored)
    report["candidate_identifiers"] = before
    report["gaps"] = []
    if not scored["enough_weeks_to_select"]:
        report["gaps"].append(
            f"Scored validation weeks: {scored['scored_weeks']}; at least {scored['minimum_scored_weeks']} are required before a candidate is selected."
        )
    _write_selection(report)
    if model_file.exists() and not model_existed:
        raise RuntimeError("Model selection wrote the Reveal model before the reserved final test.")
    return report


def _write_selection(report: dict) -> None:
    destination = data_dir("models") / SELECTION_REPORT
    destination.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _write_candidate_report(report: dict) -> None:
    destination = data_dir("models") / CANDIDATE_REPORT
    stored = {key: value for key, value in report.items() if key not in {"prepared", "train"}}
    destination.write_text(json.dumps(stored, indent=2, default=str), encoding="utf-8")


def _clear_candidates() -> None:
    folder = data_dir("models")
    for filename in CANDIDATE_FILES.values():
        path = folder / filename
        if path.exists():
            path.unlink()


def run_training(table_path: Path, config: dict | None = None) -> dict:
    cfg = config or settings()
    report = {
        "data_origin": None,
        "table": str(table_path),
        "feature_columns": list(FEATURE_COLUMNS),
        "split": {
            "train_years": cfg["train_years"],
            "tune_years": cfg["tune_years"],
            "test_years": cfg["test_years"],
        },
        "reserved_role": "transfer",
        "gaps": [],
        "chosen_model": None,
        "validation": {},
        "temporal_test": None,
        "transfer_evaluation": None,
        "thresholds": {},
    }
    if not table_path.is_file():
        report["gaps"].append(
            f"No paired-cell table at {table_path}. Process NASA swaths before training."
        )
        _write_report(report)
        return report
    frame = supported_platform_rows(pd.read_parquet(table_path), cfg)
    if frame.empty or "data_origin" not in frame.columns or not bool((frame["data_origin"] == "nasa").all()):
        report["data_origin"] = "not_nasa"
        report["gaps"].append(
            "Training refused because the table is empty or is not marked as NASA observations."
        )
        _write_report(report)
        return report
    report["data_origin"] = "nasa"
    prepared = _prepare(frame, cfg)
    development = prepared[prepared["role"] == "train"]
    transfer = prepared[prepared["role"] == "transfer"]
    parts = {name: development[development["split"] == name] for name in ("train", "tune", "test")}
    train = parts["train"]
    positives = int(train["modis_detected"].astype(bool).sum()) if len(train) else 0
    train_years = sorted(set(train["iso_year"].tolist())) if len(train) else []
    train_regions = sorted(set(train["region_id"].tolist())) if len(train) else []
    tune_weeks = _weeks(parts["tune"], np.zeros(len(parts["tune"])), cfg)
    sufficient_tune = sum(1 for week in tune_weeks if week["coverage_status"] == "ok")
    report["counts"] = {
        "train_rows": int(len(train)),
        "tune_rows": int(len(parts["tune"])),
        "test_rows": int(len(parts["test"])),
        "transfer_rows": int(len(transfer)),
        "train_positives": positives,
        "train_years": train_years,
        "train_regions": train_regions,
        "sufficient_tune_weeks": sufficient_tune,
    }
    if positives < int(cfg["min_train_positives"]):
        report["gaps"].append(
            f"Training positives are {positives}; at least {cfg['min_train_positives']} are required."
        )
    if len(train_years) < int(cfg["min_train_years"]):
        report["gaps"].append(
            f"Training years present: {train_years or 'none'}; at least {cfg['min_train_years']} are required."
        )
    if len(train_regions) < int(cfg["min_train_regions"]):
        report["gaps"].append(
            f"Training regions present: {train_regions or 'none'}; at least {cfg['min_train_regions']} are required."
        )
    if sufficient_tune < int(cfg["min_tune_weeks"]):
        report["gaps"].append(
            f"Tuning weeks with sufficient coverage: {sufficient_tune}; at least {cfg['min_tune_weeks']} are required."
        )
    if report["gaps"]:
        report["chosen_model"] = None
        _write_report(report)
        _clear_model()
        return report

    fitted = _fit(train, cfg)
    observed_only = train.copy()
    observed_only["probability"] = observed_only["modis_detected"].astype(float)
    thresholds = _fit_thresholds(_weeks(observed_only, observed_only["probability"].to_numpy(), cfg), cfg)
    validation = {}
    for name in MODEL_ORDER:
        probability = _probabilities(name, fitted[name], parts["tune"])
        validation[name] = _score(_weeks(parts["tune"], probability, cfg), thresholds)
    eligible_models = [
        name
        for name, score in validation.items()
        if score["weekly_mae_percentage_points"] is not None
    ]
    if not eligible_models:
        report["gaps"].append("No validation model produced a weekly error because coverage was insufficient.")
        report["validation"] = validation
        _write_report(report)
        _clear_model()
        return report
    chosen = sorted(
        eligible_models,
        key=lambda name: (
            validation[name]["weekly_mae_percentage_points"],
            MODEL_ORDER.index(name),
        ),
    )[0]
    test_probability = _probabilities(chosen, fitted[chosen], parts["test"])
    temporal = _score(_weeks(parts["test"], test_probability, cfg), thresholds)
    transfer_score = None
    if len(transfer):
        transfer_probability = _probabilities(chosen, fitted[chosen], transfer)
        transfer_score = _score(_weeks(transfer, transfer_probability, cfg), thresholds)
    artifact = {
        "model_name": chosen,
        "pipeline": fitted[chosen],
        "feature_columns": list(FEATURE_COLUMNS),
        "thresholds": thresholds,
        "training_regions": train_regions,
        "seed": int(cfg["seed"]),
        "supported_platform": cfg["supported_platform"],
    }
    model_file = data_dir("models") / MODEL_PATH
    joblib.dump(artifact, model_file)
    report.update(
        {
            "chosen_model": chosen,
            "validation": validation,
            "temporal_test": temporal,
            "transfer_evaluation": transfer_score,
            "thresholds": thresholds,
            "model_file": str(model_file),
            "tie_break": "Lower weekly mean absolute error wins. Ties prefer raw VIIRS, then logistic regression, then random forest.",
        }
    )
    _write_report(report)
    return report


def _write_report(report: dict) -> None:
    destination = data_dir("models") / REPORT_PATH
    destination.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _clear_model() -> None:
    path = data_dir("models") / MODEL_PATH
    if path.exists():
        path.unlink()
