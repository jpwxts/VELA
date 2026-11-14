"""Fair six-classifier comparison utilities for Philippine onset forecasts.

These helpers are imported by the training script once verified labels exist.
They are unit-tested on tiny synthetic matrices so the comparison protocol stays
reproducible without publishing a Philippine wildfire percentage.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.tree import DecisionTreeClassifier


CLASSIFIER_NAMES = (
    "logistic_regression",
    "decision_tree",
    "random_forest",
    "extra_trees",
    "hist_gradient_boosting",
    "calibrated_svm",
)


def build_classifiers(random_state: int = 0, *, cv_folds: int = 3) -> dict[str, Any]:
    folds = max(2, int(cv_folds))
    return {
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=400,
                        class_weight=None,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        "decision_tree": DecisionTreeClassifier(
            max_depth=4,
            min_samples_leaf=2,
            random_state=random_state,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=80,
            max_depth=6,
            min_samples_leaf=2,
            n_jobs=1,
            random_state=random_state,
        ),
        "extra_trees": ExtraTreesClassifier(
            n_estimators=80,
            max_depth=6,
            min_samples_leaf=2,
            n_jobs=1,
            random_state=random_state,
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_depth=4,
            learning_rate=0.08,
            max_iter=80,
            random_state=random_state,
        ),
        "calibrated_svm": CalibratedClassifierCV(
            estimator=Pipeline(
                [
                    ("scale", StandardScaler()),
                    ("clf", LinearSVC(max_iter=4000, dual="auto", random_state=random_state)),
                ]
            ),
            method="sigmoid",
            cv=folds,
        ),
    }


def seasonal_baseline_probs(y_train: np.ndarray, season_keys_train, season_keys_eval) -> np.ndarray:
    """Regional seasonal event-rate baseline; preserves natural frequency on eval."""

    rates: dict[Any, float] = {}
    for key, label in zip(season_keys_train, y_train):
        rates.setdefault(key, []).append(float(label))
    mean_rates = {key: float(np.mean(vals)) for key, vals in rates.items()}
    global_rate = float(np.mean(y_train)) if len(y_train) else 0.0
    return np.asarray([mean_rates.get(key, global_rate) for key in season_keys_eval], dtype=float)


def predict_proba_positive(model, x: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x)
        if proba.ndim == 2 and proba.shape[1] >= 2:
            return proba[:, 1]
        return proba.ravel()
    if hasattr(model, "decision_function"):
        scores = model.decision_function(x)
        return 1.0 / (1.0 + np.exp(-scores))
    raise TypeError(f"Model {type(model)!r} cannot produce probabilities.")


def classification_report_block(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    threshold: float,
    baseline_prob: np.ndarray | None = None,
) -> dict[str, Any]:
    y_hat = (y_prob >= threshold).astype(int)
    positive_count = int(np.sum(y_true == 1))
    matrix = confusion_matrix(y_true, y_hat, labels=[0, 1]).tolist()
    precision, recall, _ = precision_recall_curve(y_true, y_prob)
    brier = float(brier_score_loss(y_true, y_prob)) if len(y_true) else None
    baseline_brier = None
    if baseline_prob is not None and len(y_true):
        baseline_brier = float(brier_score_loss(y_true, baseline_prob))
    return {
        "threshold": threshold,
        "positive_event_count": positive_count,
        "brier_score": brier,
        "baseline_brier_score": baseline_brier,
        "brier_skill_vs_baseline": None
        if brier is None or baseline_brier in (None, 0)
        else float(1.0 - (brier / baseline_brier)),
        "precision": float(precision_score(y_true, y_hat, zero_division=0)),
        "recall": float(recall_score(y_true, y_hat, zero_division=0)),
        "f1": float(f1_score(y_true, y_hat, zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_hat)),
        "confusion_matrix_labels": [0, 1],
        "confusion_matrix": matrix,
        "pr_curve_points": int(len(precision)),
    }


def choose_threshold_on_validation(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    *,
    grid: np.ndarray | None = None,
) -> float:
    """Choose an alert threshold on validation by maximum F1 (recorded before holdout)."""

    candidates = grid if grid is not None else np.linspace(0.05, 0.95, 19)
    best_t = 0.5
    best_f1 = -1.0
    for threshold in candidates:
        y_hat = (y_prob >= threshold).astype(int)
        score = float(f1_score(y_true, y_hat, zero_division=0))
        if score > best_f1:
            best_f1 = score
            best_t = float(threshold)
    return best_t


def compare_on_validation(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_valid: np.ndarray,
    y_valid: np.ndarray,
    *,
    season_keys_train,
    season_keys_valid,
    random_state: int = 0,
) -> dict[str, Any]:
    """Fit each classifier on train; score on validation; pick by Brier vs baseline."""

    baseline = seasonal_baseline_probs(y_train, season_keys_train, season_keys_valid)
    baseline_metrics = classification_report_block(
        y_valid, baseline, threshold=0.5, baseline_prob=baseline
    )
    rows = []
    positive_count = int(np.sum(y_train == 1))
    cv_folds = max(2, min(3, positive_count)) if positive_count else 2
    models = build_classifiers(random_state=random_state, cv_folds=cv_folds)
    for name, model in models.items():
        try:
            model.fit(x_train, y_train)
            proba = predict_proba_positive(model, x_valid)
        except Exception as exc:  # noqa: BLE001 - keep comparison going if one family fails
            rows.append(
                {
                    "name": name,
                    "threshold": None,
                    "metrics": None,
                    "fit_error": str(exc),
                }
            )
            continue
        threshold = choose_threshold_on_validation(y_valid, proba)
        metrics = classification_report_block(
            y_valid, proba, threshold=threshold, baseline_prob=baseline
        )
        rows.append({"name": name, "threshold": threshold, "metrics": metrics})
    # Winner: lowest Brier; tie-break by higher brier skill vs baseline. Never by |acc-F1|.
    def sort_key(row: dict) -> tuple:
        m = row.get("metrics") or {}
        brier = m["brier_score"] if m.get("brier_score") is not None else 1e9
        skill = m["brier_skill_vs_baseline"] if m.get("brier_skill_vs_baseline") is not None else -1e9
        return (brier, -skill)

    ranked = sorted([row for row in rows if row.get("metrics")], key=sort_key)
    winner = ranked[0] if ranked else None
    return {
        "baseline": {"name": "regional_seasonal_event_rate", "metrics": baseline_metrics},
        "classifiers": rows,
        "winner": None
        if winner is None
        else {
            "name": winner["name"],
            "threshold": winner["threshold"],
            "why": (
                "Lowest validation Brier score relative to the seasonal baseline, "
                "with calibration inspected via Brier; not chosen by accuracy≈F1."
            ),
            "metrics": winner["metrics"],
        },
    }
