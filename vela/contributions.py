"""One calendar contribution per adequately observed cell-day.

Aqua supplies the cell-day when its coverage is eligible, including a clear
zero. Otherwise one VIIRS platform is selected by visible land, then by
closeness to the 13:30 Aqua overpass. Hotspot counts never enter that order.
NOAA-20 and NOAA-21 stay identifiable. Their raw observations remain, and
their harmonized estimates stay calibration pending until a measured
platform-transfer result exists.
"""

from __future__ import annotations

from vela.settings import settings

AQUA = "Aqua"
VIIRS_PLATFORMS = ("Suomi-NPP", "NOAA-20", "NOAA-21")
CALIBRATION_PENDING_PLATFORMS = frozenset({"NOAA-20", "NOAA-21"})
PLATFORM_TIE = {"Aqua": 0, "Suomi-NPP": 1, "NOAA-20": 2, "NOAA-21": 3}

CONTRIBUTION_RULE = (
    "Each adequately observed cell-day contributes once. "
    "Aqua supplies the contribution when it is eligible. "
    "Otherwise one VIIRS platform is selected by visible-land coverage, then by closeness to 13:30 local time. "
    "Hotspot count is not used. "
    "NOAA-20 and NOAA-21 raw observations stay visible, and their harmonized estimates stay calibration pending "
    "until a measured transfer result exists."
)

CALIBRATION_PENDING = "calibration pending"
OBSERVED_AQUA = "observed Aqua activity"
RAW_VIIRS = "raw VIIRS activity"
CALIBRATED_VIIRS = "calibrated VIIRS estimate"
UNAVAILABLE = "unavailable"
METHOD_NAMES = (OBSERVED_AQUA, RAW_VIIRS, CALIBRATED_VIIRS, UNAVAILABLE)


def method_name(contribution: dict) -> str:
    """Name the value that supplied one selected cell-day.

    Aqua is an observation, including a clear zero. Suomi-NPP's fire detection
    is raw VIIRS activity until a selected model supplies a calibrated value.
    NOAA-20 and NOAA-21 stay unavailable while their calibration is pending.
    """

    platform = contribution.get("platform")
    if platform in CALIBRATION_PENDING_PLATFORMS:
        return UNAVAILABLE
    if platform == AQUA:
        return OBSERVED_AQUA
    if contribution.get("calibrated_value") is not None:
        return CALIBRATED_VIIRS
    if platform in VIIRS_PLATFORMS:
        return RAW_VIIRS
    return UNAVAILABLE


def _visible_rank(observation: dict) -> tuple:
    return (
        float(observation.get("visible_km2") or 0),
        -float(observation.get("hours_from_aqua") or 0),
        -PLATFORM_TIE.get(observation.get("platform"), 9),
    )


def harmonized_label(platform: str) -> str:
    if platform in CALIBRATION_PENDING_PLATFORMS:
        return CALIBRATION_PENDING
    if platform == AQUA:
        return OBSERVED_AQUA
    return RAW_VIIRS


def select_one(observations: list[dict]) -> dict | None:
    """Choose the single contribution for observations of one cell-day.

    The order is visible land, then closeness to 13:30 local time, then a
    fixed platform order. Hotspot count is not in that order.
    """

    eligible = [item for item in observations if item.get("eligible")]
    aqua = [item for item in eligible if item.get("platform") == AQUA]
    if aqua:
        chosen = _contribution(max(aqua, key=_visible_rank), "aqua_when_eligible")
    else:
        viirs = [item for item in eligible if item.get("platform") in VIIRS_PLATFORMS]
        if not viirs:
            return None
        chosen = _contribution(max(viirs, key=_visible_rank), "viirs_coverage_and_time")
    reasons = sorted(
        {
            str(item.get("ineligible_reason"))
            for item in observations
            if item.get("platform") == AQUA and not item.get("eligible") and item.get("ineligible_reason")
        }
    )
    chosen["aqua_ineligible_reason"] = reasons[0] if reasons else None
    return chosen


def _contribution(observation: dict, rule: str) -> dict:
    platform = observation["platform"]
    detected = observation.get("detected")
    return {
        "cell_id": observation.get("cell_id"),
        "local_date": str(observation.get("local_date") or "")[:10],
        "platform": platform,
        "detected": None if detected is None else bool(detected),
        "rule": rule,
        "estimate_status": "calibration_pending" if platform in CALIBRATION_PENDING_PLATFORMS else (
            "observed" if platform == AQUA else "raw"
        ),
        "harmonized_estimate": harmonized_label(platform),
        "method": method_name({"platform": platform}),
        "visible_km2": float(observation.get("visible_km2") or 0),
        "hours_from_aqua": float(observation.get("hours_from_aqua") or 0),
        "hotspot_pixel_count": int(observation.get("hotspot_pixel_count") or 0),
        "source_index": observation.get("source_index"),
        "bounds": observation.get("bounds"),
    }


def _binary(value) -> float | None:
    if value is None:
        return None
    return 1.0 if bool(value) else 0.0


def activity_value(contribution: dict) -> float | None:
    """Value that enters the activity-estimate total.

    Observed Aqua activity enters, including a clear zero. A calibrated VIIRS
    estimate enters when a selected model supplied one. Raw VIIRS activity enters
    only when raw VIIRS is the selected method. NOAA calibration-pending stays out.
    """

    method = contribution.get("method") or method_name(contribution)
    if method == OBSERVED_AQUA:
        return _binary(contribution.get("detected"))
    if method == CALIBRATED_VIIRS:
        value = contribution.get("calibrated_value")
        return None if value is None else float(value)
    if method == RAW_VIIRS and contribution.get("selected_method") == "raw_viirs":
        return _binary(contribution.get("detected"))
    return None


def raw_activity_value(contribution: dict) -> float | None:
    """The observed raw VIIRS detection. It stays visible beside any model probability."""

    platform = contribution.get("platform")
    if platform not in VIIRS_PLATFORMS or platform in CALIBRATION_PENDING_PLATFORMS:
        return None
    return _binary(contribution.get("detected"))


def tally_activity(contributions: list[dict], config: dict | None = None) -> dict:
    """Count eligible coverage separately from cell-days that have an activity estimate."""

    cfg = config or settings()
    minimum = int(cfg["min_usable_cell_days_per_week"])
    minimum_fraction = float(cfg["min_shared_coverage"])
    cell_area = float(cfg["cell_area_km2"])
    coverage = len(contributions)
    counts = {name: 0 for name in METHOD_NAMES}
    for item in contributions:
        counts[item.get("method") or method_name(item)] += 1
    values = [value for item in contributions if (value := activity_value(item)) is not None]
    estimated = len(values)
    mean_fraction = None
    if coverage and cell_area:
        mean_fraction = sum(float(item.get("visible_km2") or 0) for item in contributions) / coverage / cell_area
    established = coverage >= minimum and mean_fraction is not None and mean_fraction + 1e-12 >= minimum_fraction
    if estimated == 0:
        status = "unavailable"
        rate = None
        denominator = None
    elif estimated < coverage:
        status = "partial"
        rate = sum(values) / estimated
        denominator = estimated
    else:
        status = "complete"
        rate = sum(values) / coverage
        denominator = coverage
    return {
        "eligible_coverage_cell_days": coverage,
        "method_counts": counts,
        "activity_estimate_cell_days": estimated,
        "activity_denominator": denominator,
        "activity_rate": rate,
        "activity_status": status,
        "clear_zero": bool(status == "complete" and rate == 0.0 and established),
        "coverage_established": established,
        "mean_supplying_coverage": mean_fraction,
    }


def present_scene(observations: list[dict]) -> dict:
    """Keep every native point, and count each adequately observed cell-day once."""

    grouped: dict[tuple, list] = {}
    points = []
    for observation in observations:
        key = (observation.get("cell_id"), str(observation.get("local_date") or "")[:10])
        grouped.setdefault(key, []).append(observation)
        points.extend(observation.get("points") or [])
    contributions = []
    for group in grouped.values():
        chosen = select_one(group)
        if chosen is not None:
            contributions.append(chosen)
    return {
        "map_points": points,
        "contributions": contributions,
        "cell_days": len(contributions),
        "rule": CONTRIBUTION_RULE,
    }


def cell_detail(contribution: dict, held_out: bool = False) -> dict:
    """What a click on the cell is allowed to show."""

    platform = contribution["platform"]
    hide_detection = bool(held_out and platform == AQUA)
    detected = None if hide_detection else contribution.get("detected")
    method = contribution.get("method") or method_name(contribution)
    estimate = activity_value(contribution)
    raw_value = raw_activity_value(contribution)
    if hide_detection:
        estimate = None
        if method == OBSERVED_AQUA:
            raw_value = None
    pending = method == UNAVAILABLE
    if method == UNAVAILABLE:
        label = "unavailable"
    elif estimate is None:
        label = "unavailable" if raw_value is None else None
    elif method == CALIBRATED_VIIRS:
        label = f"{estimate:.4f}"
    else:
        label = f"{estimate:.0f}"
    return {
        "cell_id": contribution.get("cell_id"),
        "local_date": contribution.get("local_date"),
        "platform": platform,
        "supplied_by": f"{platform} supplied this cell-day.",
        "rule": contribution.get("rule"),
        "detected": detected,
        "detection_hidden": hide_detection,
        "method": method,
        "selected_method": contribution.get("selected_method"),
        "harmonized_estimate": contribution.get("harmonized_estimate") or harmonized_label(platform),
        "activity_estimate": estimate,
        "raw_activity": raw_value,
        "activity_label": label,
        "model_probability": contribution.get("calibrated_value") if method == CALIBRATED_VIIRS else None,
        "aqua_ineligible_reason": contribution.get("aqua_ineligible_reason"),
        "visible_km2": contribution.get("visible_km2"),
        "hours_from_aqua": contribution.get("hours_from_aqua"),
        "hotspot_pixel_count": contribution.get("hotspot_pixel_count"),
        "hotspot_count_used": False,
        "bounds": contribution.get("bounds"),
        "calibration_pending": pending,
    }


def _number(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if value != value:  # NaN
            return default
    except TypeError:
        return default
    return float(value)


def _flag(value):
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        return None
    return bool(value)


def _threshold(config: dict | None = None) -> float:
    cfg = config or settings()
    return float(cfg["min_shared_coverage"]) * float(cfg["cell_area_km2"])


def _sensor_reason(visible_km2: float, threshold: float, empty_reason: str, short_reason: str) -> str | None:
    if visible_km2 + 1e-12 >= threshold:
        return None
    if visible_km2 <= 0:
        return empty_reason
    return short_reason


def observations_from_paired_row(row: dict, source_index: int = 0, config: dict | None = None) -> list[dict]:
    """Split one stored pair into Aqua and VIIRS observations.

    A sensor can supply the cell-day only when its own visible land covers at
    least half of the 5 km cell. Older rows have no platform column. Those
    VIIRS observations are Suomi-NPP, which is the only platform in the frozen table.
    """

    cell_id = row.get("cell_id")
    local_date = str(row.get("local_date") or "")[:10]
    hours = _number(row.get("hours_from_aqua"))
    platform = row.get("viirs_platform")
    if platform is None or (isinstance(platform, float) and platform != platform) or str(platform) in {"", "nan", "None"}:
        platform = "Suomi-NPP"
    else:
        platform = str(platform)
    shared = _number(row.get("shared_visible_km2"))
    aqua_visible = _number(row.get("modis_visible_km2"), shared)
    viirs_visible = _number(row.get("viirs_visible_km2"), shared)
    threshold = _threshold(config)
    stored_reason = row.get("exclusion_reason")
    aqua_reason = _sensor_reason(aqua_visible, threshold, "missing_modis", "insufficient_aqua_land")
    if aqua_reason == "missing_modis" and stored_reason == "insufficient_shared_land":
        aqua_reason = "insufficient_aqua_land"
    viirs_reason = _sensor_reason(viirs_visible, threshold, "missing_viirs", "insufficient_viirs_land")
    aqua_detected = _flag(row.get("modis_detected"))
    viirs_count = int(_number(row.get("viirs_hotspot_pixel_count")))
    bounds = row.get("bounds")
    aqua = {
        "cell_id": cell_id,
        "local_date": local_date,
        "platform": AQUA,
        "eligible": aqua_reason is None and aqua_detected is not None,
        "ineligible_reason": None if aqua_reason is None else aqua_reason,
        "detected": aqua_detected,
        "visible_km2": aqua_visible,
        "hours_from_aqua": hours,
        "hotspot_pixel_count": int(_number(row.get("modis_hotspot_pixel_count"))),
        "source_index": source_index,
        "points": [],
        "bounds": bounds,
    }
    viirs = {
        "cell_id": cell_id,
        "local_date": local_date,
        "platform": platform,
        "eligible": viirs_reason is None,
        "ineligible_reason": viirs_reason,
        "detected": viirs_count > 0,
        "visible_km2": viirs_visible,
        "hours_from_aqua": hours,
        "hotspot_pixel_count": viirs_count,
        "source_index": source_index,
        "points": list(row.get("points") or []),
        "bounds": bounds,
    }
    return [aqua, viirs]


def contributions_for_rows(rows: list[dict]) -> dict:
    observations = []
    for index, row in enumerate(rows):
        observations.extend(observations_from_paired_row(row, index))
    scene = present_scene(observations)
    chosen_indexes = []
    for contribution in scene["contributions"]:
        source = contribution.get("source_index")
        if source is not None and source not in chosen_indexes:
            chosen_indexes.append(source)
    scene["rows"] = [rows[index] for index in chosen_indexes]
    return scene


def apply_chosen_method(contributions: list[dict], rows: list[dict], chosen_model: str | None, pipeline=None) -> list[dict]:
    """Attach the selected Suomi-NPP method to VIIRS fallback contributions.

    Observed fire-pixel counts stay on the contribution. A model writes a
    probability into calibrated_value. Raw VIIRS selection counts the observed
    detection without renaming it to a calibrated estimate.
    """

    if not chosen_model:
        return contributions
    from vela.features import FEATURE_COLUMNS, feature_values, viirs_counts_from_mapping

    updated = [dict(item) for item in contributions]
    for out in updated:
        out["selected_method"] = chosen_model
        if out.get("platform") != "Suomi-NPP":
            continue
        if chosen_model == "raw_viirs":
            out["method"] = RAW_VIIRS
            out["harmonized_estimate"] = RAW_VIIRS
            out["estimate_status"] = "raw_selected"
    if chosen_model == "raw_viirs" or pipeline is None:
        return updated

    import pandas as pd

    indexes = []
    feature_rows = []
    for position, out in enumerate(updated):
        if out.get("platform") != "Suomi-NPP":
            continue
        source_index = out.get("source_index")
        if source_index is None:
            continue
        source = rows[int(source_index)]
        feature_rows.append(
            feature_values(
                viirs_counts_from_mapping(source),
                float(source.get("center_lat") or 0),
                float(source.get("center_lon") or 0),
                source.get("local_date"),
                float(source.get("local_hour") or 0),
            )
        )
        indexes.append(position)
    if not feature_rows:
        return updated
    frame = pd.DataFrame(feature_rows, columns=list(FEATURE_COLUMNS))
    probabilities = pipeline.predict_proba(frame)[:, 1]
    for position, probability in zip(indexes, probabilities):
        out = updated[position]
        out["calibrated_value"] = float(probability)
        out["method"] = CALIBRATED_VIIRS
        out["harmonized_estimate"] = CALIBRATED_VIIRS
        out["estimate_status"] = "calibrated"
    return updated
