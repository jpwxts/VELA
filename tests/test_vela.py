from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from app.db import ResponseCache
from app.firms import FirmsClient
from vela.calendar_metrics import CALENDAR_METRIC, summarize_week
from vela.coverage import classify_cell
from vela.features import FEATURE_COLUMNS, assert_feature_contract, feature_values, raw_viirs_active
from vela.geo import firms_boxes, in_bbox
from vela.grid import center, indices, pack, unpack
from vela.harmonize import choose_one
from vela.masks import empty_counts, hotspot_count, summarize
from vela.sample import build_manifest
from vela.settings import settings
from vela.splits import split_for_year


def _counts(**updates):
    counts = empty_counts()
    counts.update(updates)
    return counts


AVAILABILITY = """data_id,min_date,max_date
MODIS_SP,2000-11-01,2024-12-31
MODIS_NRT,2025-01-01,2026-12-31
VIIRS_SNPP_SP,2012-01-20,2024-12-31
VIIRS_SNPP_NRT,2025-01-01,2026-12-31
VIIRS_NOAA20_SP,2018-04-01,2024-12-31
VIIRS_NOAA20_NRT,2025-01-01,2026-12-31
VIIRS_NOAA21_SP,2024-01-01,2024-12-31
VIIRS_NOAA21_NRT,2025-01-01,2026-12-31
"""

MODIS_CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight
-15.0,-50.0,320,1,1,2019-08-20,1740,Aqua,MODIS,80,6.1,300,12.5,D
-15.1,-50.1,310,1,1,2019-08-20,1510,Terra,MODIS,70,6.1,290,8.0,D
"""

HEADER = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight\n"


def test_fire_mask_codes_keep_modis_and_viirs_class_two_apart():
    assert summarize([2], "modis")["missing"] == 1
    assert summarize([2], "viirs")["unknown"] == 1
    assert hotspot_count(summarize([7, 8, 9, 5], "viirs")) == 3


def test_viirs_netcdf_solar_zenith_is_scaled_once():
    """Packed VIIRS solar_zenith uses scale_factor 0.01. netCDF4 must not scale twice."""

    from pathlib import Path

    import netCDF4

    from vela.readers import open_science

    path = Path("data/raw/yakutia/2021-11-22/VNP03IMG.A2021326.0248.002.2021326095111.nc")
    if not path.is_file():
        pytest.skip("cached Yakutia geolocation granule is not on disk")
    with netCDF4.Dataset(path) as dataset:
        variable = dataset.groups["geolocation_data"].variables["solar_zenith"]
        variable.set_auto_scale(False)
        raw = np.asarray(variable[0:20, :], dtype=np.float64)
        scale = float(variable.scale_factor)
        expected = float(np.nanmedian(raw * scale))
    science = open_science(path)
    try:
        zenith = science.zenith()
        assert zenith is not None
        values = np.asarray(zenith.read_scaled(0, 20), dtype=np.float64)
        finite = values[np.isfinite(values)]
        assert finite.size
        median = float(np.median(finite))
        assert 60.0 <= median <= 95.0
        assert median == pytest.approx(expected, rel=0, abs=0.05)
        assert median > 10.0
    finally:
        science.close()


def test_missing_viirs_platform_defaults_to_suomi():
    from vela.contributions import observations_from_paired_row

    rows = observations_from_paired_row(
        {
            "cell_id": "1:1",
            "local_date": "2021-07-22",
            "viirs_platform": float("nan"),
            "modis_visible_km2": 0,
            "viirs_visible_km2": 20,
            "shared_visible_km2": 0,
            "modis_detected": None,
            "viirs_hotspot_pixel_count": 0,
            "hours_from_aqua": 0.5,
            "exclusion_reason": "missing_modis",
        }
    )
    assert rows[1]["platform"] == "Suomi-NPP"
    assert rows[1]["eligible"] is True


def test_cloudy_cell_is_zero_visible_land_not_a_missing_observation():
    cloudy = classify_cell(_counts(cloud=20), _counts(cloud=100, missing=20))
    assert cloudy["modis_visible_km2"] == 0.0
    assert cloudy["viirs_visible_km2"] == 0.0
    assert cloudy["shared_visible_km2"] == 0.0
    assert cloudy["exclusion_reason"] == "insufficient_shared_land"
    assert cloudy["modis_counts"]["cloud"] == 20
    assert cloudy["viirs_counts"]["cloud"] == 100


def test_clear_zero_is_not_the_same_as_missing_coverage():
    modis = _counts(clear=20)
    viirs = _counts(clear=100)
    clear = classify_cell(modis, viirs)
    assert clear["eligible"] is True
    assert clear["outcome"] == "neither"
    assert clear["modis_detected"] is False

    missing = classify_cell(_counts(missing=20), viirs)
    assert missing["eligible"] is False
    assert missing["exclusion_reason"] == "missing_modis"
    assert missing["outcome"] is None
    assert missing["modis_detected"] is None

    cloudy = classify_cell(_counts(cloud=30), _counts(cloud=100))
    assert cloudy["exclusion_reason"] == "insufficient_shared_land"
    assert cloudy["outcome"] is None


def test_august_23_stays_visible_with_a_missing_rate():
    from vela.calendar_metrics import missing_rate_dates

    dates = missing_rate_dates({"2019-08-20", "2019-08-21", "2019-08-24"}, {"2019-08-20", "2019-08-23"})
    assert dates == [{"local_date": "2019-08-23", "coverage_status": "insufficient", "rate": None}]


def test_validation_preselect_keeps_quiet_weeks_and_pantanal_out():
    from vela.expansion import select_validation_weeks

    rows = []
    for region, role, split in (
        ("cerrado", "train", "tune"),
        ("california", "train", "tune"),
        ("pantanal", "transfer", "tune"),
    ):
        for year in (2021, 2022):
            for season, quiet in (("DJF", "yes"), ("MAM", "no"), ("JJA", "no"), ("SON", "no")):
                rows.append(
                    {
                        "region_id": region,
                        "role": role,
                        "development": "no" if role == "transfer" else "yes",
                        "split": split,
                        "year": year,
                        "season": season,
                        "quiet": quiet,
                        "week_start": f"{region}-{year}-{season}",
                        "week_end": f"{region}-{year}-{season}-end",
                    }
                )
    selection = select_validation_weeks(rows, seed=42)
    chosen = selection["primary"] + selection["reserves"]
    assert all(row["region_id"] != "pantanal" for row in chosen)
    assert all(int(row["year"]) in (2021, 2022) for row in chosen)
    assert any(row["quiet"] == "yes" for row in selection["primary"])
    primary_keys = {(row["region_id"], row["week_start"]) for row in selection["primary"]}
    assert all((row["region_id"], row["week_start"]) not in primary_keys for row in selection["reserves"])


def test_global_plan_selects_training_weeks_and_keeps_regions_reserved():
    from vela.geo import boxes_overlap
    from vela.global_plan import (
        choose_budget_weeks,
        load_plan,
        proposed_regions,
        region_order,
        select_plan_weeks,
    )
    from vela.sample import build_manifest
    from vela.settings import regions

    plan = load_plan()
    existing = build_manifest(42)
    proposed = build_manifest(42, region_list=proposed_regions(plan))
    first = select_plan_weeks(existing + proposed, seed=42, plan=plan)
    second = select_plan_weeks(existing + proposed, seed=42, plan=plan)
    assert [row["week_start"] for row in first] == [row["week_start"] for row in second]
    assert first
    assert all(row["split"] == "train" for row in first)
    assert all(2013 <= int(row["year"]) <= 2020 for row in first)
    reserved_ids = set(next(batch["regions"] for batch in plan["batches"] if batch["id"] == "E"))
    reserved = [row for row in first if row["region_id"] in reserved_ids]
    training = [row for row in first if row["region_id"] not in reserved_ids]
    assert "pantanal" in {row["region_id"] for row in reserved}
    assert all(row["development"] == "no" and row["budget_eligible"] == "no" for row in reserved)
    assert all(row["development"] == "yes" and row["budget_eligible"] == "yes" for row in training)
    for region_id in region_order(plan):
        seasons = [row["season"] for row in first if row["region_id"] == region_id]
        assert seasons == ["DJF", "MAM", "JJA", "SON"]
    boxes = list(regions()) + proposed_regions(plan)
    for index, left in enumerate(boxes):
        left_box = (left["west"], left["south"], left["east"], left["north"])
        for right in boxes[index + 1 :]:
            right_box = (right["west"], right["south"], right["east"], right["north"])
            assert not boxes_overlap(left_box, right_box)
    weeks = [
        {"region_id": "arnhem", "week_start": "2014-01-06", "budget_eligible": "yes"},
        {"region_id": "zambia", "week_start": "2015-06-01", "budget_eligible": "yes"},
        {"region_id": "guinea_savanna", "week_start": "2016-03-07", "budget_eligible": "yes"},
        {"region_id": "pantanal", "week_start": "2017-08-07", "budget_eligible": "no"},
    ]
    results = {
        ("arnhem", "2014-01-06"): {"candidate_daytime_passes": 2, "files": {"a.hdf": 3_000_000_000}},
        ("zambia", "2015-06-01"): {"candidate_daytime_passes": 0, "files": {}},
        ("guinea_savanna", "2016-03-07"): {
            "candidate_daytime_passes": 1,
            "files": {"a.hdf": 3_000_000_000, "b.nc": 2_500_000_000},
        },
        ("pantanal", "2017-08-07"): {"candidate_daytime_passes": 4, "files": {"c.hdf": 100}},
    }
    budget = choose_budget_weeks(weeks, results, 5_000_000_000)
    assert [row["region_id"] for row in budget["weeks"]] == ["arnhem"]
    assert budget["unique_new_bytes"] == 3_000_000_000
    assert budget["stopped_before"]["region_id"] == "guinea_savanna"
    assert budget["no_paired_coverage_weeks"][0]["region_id"] == "zambia"


def test_week_summary_keeps_a_zero_only_when_coverage_is_usable():
    usable = [
        {
            "viirs_hotspot_pixel_count": 0,
            "modis_detected": False,
            "shared_coverage_fraction": 0.8,
            "local_date": "2019-08-20",
        }
        for _ in range(20)
    ]
    summary = summarize_week(usable, settings())
    assert summary["coverage_status"] == "ok"
    assert summary["clear_zero"] is True
    assert summary["observed_rate"] == 0
    assert summary["viirs_rate"] == 0

    missing = summarize_week([], settings())
    assert missing["coverage_status"] == "insufficient"
    assert missing["clear_zero"] is False
    assert missing["observed_rate"] is None

    short = summarize_week(usable[:1], settings())
    assert short["coverage_status"] == "insufficient"
    assert short["viirs_rate"] is None


def test_dateline_box_is_split_and_points_are_tested_on_both_sides():
    assert firms_boxes(170, -20, -170, -10) == [
        (170, -20, 180.0, -10),
        (-180.0, -20, -170, -10),
    ]
    selected = in_bbox([175, -175, 0], [-15, -15, -15], 170, -20, -170, -10)
    assert selected.tolist() == [True, True, False]


def test_grid_is_five_kilometres_and_round_trips():
    x_index, y_index = indices([-50.0], [-14.0])
    longitude, latitude = center(int(x_index[0]), int(y_index[0]))
    assert abs(longitude + 50) < 0.05
    assert abs(latitude + 14) < 0.05
    assert unpack(int(pack(x_index, y_index)[0])) == (int(x_index[0]), int(y_index[0]))
    assert settings()["grid_m"] == 5000
    assert settings()["cell_area_km2"] == 25


def test_year_split_and_sample_keep_the_reserved_region_out():
    assert split_for_year(2013) == "train"
    assert split_for_year(2020) == "train"
    assert split_for_year(2021) == "tune"
    assert split_for_year(2022) == "tune"
    assert split_for_year(2023) == "test"
    assert split_for_year(2024) == "test"
    assert split_for_year(2012) == "outside"
    first = build_manifest(42)
    second = build_manifest(42)
    assert [row["week_start"] for row in first] == [row["week_start"] for row in second]
    assert {row["year"] for row in first} == set(range(2013, 2025))
    assert any(row["quiet"] == "yes" for row in first)
    reserved = [row for row in first if row["role"] == "transfer"]
    assert reserved
    assert all(row["development"] == "no" for row in reserved)
    assert all(row["region_id"] == "pantanal" for row in reserved)


def test_features_are_reproducible_from_viirs_alone():
    assert_feature_contract()
    counts = _counts(clear=90, fire_high=2, cloud=8)
    values = feature_values(counts, -14.2, -50.2, "2019-08-20", 13.5)
    assert list(values) == list(FEATURE_COLUMNS)
    assert all("modis" not in name and "shared" not in name for name in values)
    assert raw_viirs_active(values) == 1.0
    assert raw_viirs_active(feature_values(_counts(clear=10), 0, 0, "2019-01-01", 12)) == 0.0


def test_pilot_activity_summary_omits_a_date_with_no_eligible_cells():
    pandas = pytest.importorskip("pandas")
    import numpy as np

    from vela.pilot import make_pilot_pipeline, training_diagnostics

    frame = pandas.DataFrame(
        {
            "local_date": ["2019-08-20", "2019-08-20", "2019-08-24"],
            "viirs_hotspot_pixel_count": [0, 3, 0],
            "modis_detected": [False, True, False],
        }
    )
    pipeline = make_pilot_pipeline()
    pipeline.fit(frame[["viirs_hotspot_pixel_count"]].to_numpy(dtype=float), [0, 1, 0])
    assert pipeline.named_steps["model"].class_weight is None
    probabilities = pipeline.predict_proba(frame[["viirs_hotspot_pixel_count"]].to_numpy(dtype=float))[:, 1]
    assert np.all((probabilities >= 0) & (probabilities <= 1))
    rows = training_diagnostics(frame, probabilities)
    assert [row["local_date"] for row in rows] == ["2019-08-20", "2019-08-24"]
    assert "2019-08-23" not in {row["local_date"] for row in rows}
    assert all(row["label"] == "training_diagnostic" for row in rows)


def test_expansion_batch_uses_manifest_fields_only():
    from vela.expansion import select_first_expansion

    rows = []
    for region, role in (("cerrado", "train"), ("california", "train"), ("pantanal", "transfer")):
        for year in (2014, 2016):
            for season in ("DJF", "MAM", "JJA", "SON"):
                rows.append(
                    {
                        "region_id": region,
                        "role": role,
                        "development": "no" if role == "transfer" else "yes",
                        "split": "train",
                        "year": year,
                        "season": season,
                        "week_start": f"{year}-01-01",
                        "week_end": f"{year}-01-07",
                    }
                )
    rows.append(
        {
            "region_id": "cerrado",
            "role": "train",
            "development": "yes",
            "split": "train",
            "year": 2019,
            "season": "JJA",
            "week_start": "2019-08-19",
            "week_end": "2019-08-25",
        }
    )
    chosen = select_first_expansion(rows, seed=42, exclude_weeks={("cerrado", "2019-08-19")})
    assert len(chosen) == 4
    assert {row["season"] for row in chosen} == {"DJF", "MAM", "JJA", "SON"}
    assert len({row["region_id"] for row in chosen}) >= 2
    assert all(row["region_id"] != "pantanal" for row in chosen)
    assert all(row["split"] == "train" for row in chosen)
    assert all(2013 <= int(row["year"]) <= 2020 for row in chosen)
    assert ("cerrado", "2019-08-19") not in {(row["region_id"], row["week_start"]) for row in chosen}


def test_zero_side_requires_clear_land_and_no_fire_class():
    from vela.traces import usable_zero

    clear = usable_zero("modis", {5: 12, 4: 2})
    assert clear["usable_land"] is True
    assert clear["fire_pixels"] == 0
    assert "class 5" in clear["text"].lower() or "Class 5" in clear["text"]
    missing = usable_zero("viirs", {0: 8, 1: 4})
    assert missing["usable_land"] is False
    fired = usable_zero("modis", {5: 10, 9: 1})
    assert fired["usable_land"] is False


def test_compacting_two_shards_counts_a_cell_day_once(tmp_path, monkeypatch):
    monkeypatch.setattr("vela.tables.DATA_DIR", tmp_path)
    from vela.tables import compact_shards, write_rows

    row = {
        "cell_id": "1:1",
        "local_date": "2019-08-20",
        "eligible": True,
        "shared_visible_km2": 13,
        "hours_from_aqua": 0.4,
        "outcome": "neither",
        "modis_detected": False,
        "exclusion_reason": None,
    }
    other = dict(row)
    other["modis_file"] = "MYD14.A2019233.1630.hdf"
    folder = tmp_path / "processed" / "shards"
    write_rows([row], folder / "cerrado_2019232_1725.parquet")
    write_rows([other], folder / "cerrado_2019233_1630.parquet")
    summary = compact_shards()
    assert summary["eligible"] == 1
    assert summary["excluded"] == 1


def test_one_observation_prefers_the_usable_pass():
    weak = {
        "cell_id": "1:1",
        "local_date": "2019-08-20",
        "eligible": False,
        "shared_visible_km2": 1,
        "hours_from_aqua": 0.1,
        "outcome": None,
        "modis_detected": None,
    }
    strong = {
        "cell_id": "1:1",
        "local_date": "2019-08-20",
        "eligible": True,
        "shared_visible_km2": 13,
        "hours_from_aqua": 1,
        "outcome": "neither",
        "modis_detected": False,
    }
    kept, dropped = choose_one([weak, strong])
    assert kept == [strong]
    assert dropped[0]["exclusion_reason"] == "duplicate_pass_not_selected"
    assert dropped[0]["modis_detected"] is None


def _page_scripts():
    from pathlib import Path

    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path("app/static/js").glob("*.js")))


def test_page_language_does_not_call_the_metric_burned_area():
    from pathlib import Path

    page = Path("app/static/index.html").read_text(encoding="utf-8")
    script = _page_scripts()
    assert CALENDAR_METRIC in page
    assert "Panay" not in page and "Panay" not in script
    assert "Reveal MODIS" in script
    assert "percentage of land burned" in page


def _client(tmp_path, getter, key="SECRET-KEY-99"):
    return FirmsClient(key, ResponseCache(tmp_path / "firms.sqlite"), getter)


def _plant_cache(tmp_path, cache_key, kind, payload, hours_old):
    import sqlite3
    from datetime import datetime, timedelta, timezone

    ResponseCache(tmp_path / "firms.sqlite")  # creates the table
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat()
    with sqlite3.connect(tmp_path / "firms.sqlite") as connection:
        connection.execute(
            "INSERT OR REPLACE INTO response_cache VALUES (?, ?, ?, ?)",
            (cache_key, kind, payload, stamp),
        )


def _availability_key(key="SECRET-KEY-99"):
    import hashlib

    from app.firms import _cache_key

    return _cache_key("availability", hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], "all", (0, 0, 0, 0))


def _modis_nrt_list(last_day):
    return f"data_id,min_date,max_date\nMODIS_NRT,2025-01-01,{last_day}\n"


def _aqua_row(day):
    return f"{HEADER}-15.0,-50.0,320,1,1,{day},0540,Aqua,MODIS,80,6.1NRT,300,12.5,D\n"


def test_a_day_newer_than_the_cached_list_rechecks_the_list(tmp_path):
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    # Cached two hours ago, before NASA published yesterday's file.
    _plant_cache(tmp_path, _availability_key(), "availability",
                 _modis_nrt_list((today - timedelta(days=2)).isoformat()), hours_old=2)
    calls = []

    def getter(url: str):
        calls.append(url)
        if "data_availability" in url:
            return 200, _modis_nrt_list(today.isoformat())
        if "/MODIS_NRT/" in url:
            return 200, _aqua_row(yesterday)
        raise AssertionError(url)

    result = _client(tmp_path, getter).hotspots(-50.5, -15.5, -49.5, -14.5, yesterday, ["Aqua"])

    assert sum("data_availability" in url for url in calls) == 1
    assert result["results"][0]["processing"] == "near_real_time"
    assert result["total_count"] == 1


def test_the_list_is_not_rechecked_too_often_or_for_future_days(tmp_path):
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    two_days_ago = (today - timedelta(days=2)).isoformat()

    def getter(url: str):
        raise AssertionError(f"unexpected request {url}")

    # Rechecked five minutes ago: wait before asking again.
    _plant_cache(tmp_path, _availability_key(), "availability", _modis_nrt_list(two_days_ago), hours_old=5 / 60)
    recent = _client(tmp_path, getter).hotspots(-50.5, -15.5, -49.5, -14.5, (today - timedelta(days=1)).isoformat(), ["Aqua"])
    assert recent["results"][0]["status"] == "product_unavailable"

    # A future day cannot be published yet, however old the list is.
    _plant_cache(tmp_path, _availability_key(), "availability", _modis_nrt_list(today.isoformat()), hours_old=2)
    future = _client(tmp_path, getter).hotspots(-50.5, -15.5, -49.5, -14.5, (today + timedelta(days=1)).isoformat(), ["Aqua"])
    assert future["results"][0]["status"] == "product_unavailable"


def test_a_recent_days_empty_answer_is_not_reused_for_hours(tmp_path):
    from datetime import datetime, timedelta, timezone

    from app.firms import _cache_key
    from vela.geo import firms_boxes, round_box

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    _plant_cache(tmp_path, _availability_key(), "availability", _modis_nrt_list(today.isoformat()), hours_old=0.1)
    # Asked 45 minutes ago, before the afternoon pass was published: nothing yet.
    (piece,) = list(firms_boxes(*round_box(-50.5, -15.5, -49.5, -14.5)))
    _plant_cache(tmp_path, _cache_key("area", "MODIS_NRT", yesterday, piece), "area", HEADER, hours_old=0.75)

    def getter(url: str):
        if "/MODIS_NRT/" in url:
            return 200, _aqua_row(yesterday)
        raise AssertionError(url)

    result = _client(tmp_path, getter).hotspots(-50.5, -15.5, -49.5, -14.5, yesterday, ["Aqua"])

    assert result["total_count"] == 1
    assert result["results"][0]["cached"] is False


def test_aqua_filter_uses_standard_processing_and_hides_the_key(tmp_path):
    calls = []

    def getter(url: str):
        calls.append(url)
        if "data_availability" in url:
            return 200, AVAILABILITY
        if "/MODIS_SP/" in url:
            return 200, MODIS_CSV
        raise AssertionError(url)

    result = _client(tmp_path, getter).hotspots(-52.5, -15.5, -48.5, -12.5, "2019-08-20", ["Aqua"])
    encoded = json.dumps(result)
    assert "SECRET-KEY-99" not in encoded
    assert result["total_count"] == 1
    assert result["results"][0]["platform"] == "Aqua"
    assert result["results"][0]["count"] == len(result["results"][0]["hotspots"])
    assert result["results"][0]["processing"] == "standard"
    assert result["results"][0]["coverage"] == "unknown"
    assert result["results"][0]["hotspots"][0]["instrument"] == "MODIS"
    assert all("/MODIS_NRT/" not in url for url in calls)
    assert any("/MODIS_SP/" in url and "/1/2019-08-20" in url for url in calls)


def test_empty_csv_is_no_hotspots_and_not_a_failed_request(tmp_path):
    def getter(url: str):
        if "data_availability" in url:
            return 200, AVAILABILITY
        return 200, HEADER

    result = _client(tmp_path, getter).hotspots(0, 0, 1, 1, "2019-08-20", ["Aqua"])
    status = result["results"][0]
    assert status["status"] == "no_hotspots"
    assert status["coverage"] == "unknown"
    assert status["count"] == 0


def _observation(**updates):
    observation = {
        "cell_id": "1:1",
        "local_date": "2021-02-25",
        "platform": "Suomi-NPP",
        "eligible": True,
        "detected": False,
        "visible_km2": 15,
        "hours_from_aqua": 0.4,
        "hotspot_pixel_count": 0,
        "points": [],
    }
    observation.update(updates)
    return observation


def test_all_feeds_empty_with_unknown_coverage_leave_harmonized_activity_unavailable(tmp_path):
    def getter(url: str):
        if "data_availability" in url:
            return 200, AVAILABILITY
        return 200, HEADER

    result = _client(tmp_path, getter).hotspots(
        0, 0, 1, 1, "2024-06-01", ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"]
    )
    combined = result["combined"]
    assert result["total_count"] == 0
    assert combined["raw_detection_records"] == 0
    assert combined["feeds_queried"] == 4
    assert combined["feeds_unavailable"] == 0
    assert combined["coverage"] == "unknown"
    assert combined["harmonized_activity"] == "unavailable"
    assert combined["harmonized_activity_label"] == (
        "Harmonized activity is unavailable until coverage is established."
    )
    assert all(row["coverage"] == "unknown" for row in result["results"])
    assert all(row["status"] == "no_hotspots" for row in result["results"])
    assert result["public_result"]["kind"] == "unknown_empty"
    assert "don’t know how much" in result["public_result"]["text"]
    assert result["hotspot_areas"]["area_count"] == 0


def test_hotspot_areas_group_by_cell_and_count_spacecraft_separately(tmp_path):
    from vela.grid import indices

    x_index, y_index = indices(-50.1, -14.2)
    lon = -50.1
    lat = -14.2
    other_lon, other_lat = -49.5, -13.8

    def row(satellite, time, lon_value=lon, lat_value=lat, frp="10.0"):
        return (
            f"{lat_value},{lon_value},330,1,1,2024-06-01,{time},{satellite},"
            f"MODIS,nominal,6.1NRT,290,{frp},D"
        )

    body = HEADER + "\n".join(
        [
            row("Aqua", "1300"),
            row("Aqua", "1300"),  # identical duplicate
            row("Aqua", "1315"),
            row("Aqua", "1330"),
            row("Aqua", "1345"),
            row("Aqua", "1400"),
            row("Aqua", "1415"),
            row("Aqua", "1430"),
            row("Aqua", "1445"),
            row("Aqua", "1500"),
            row("Aqua", "1515"),  # ten Aqua pixels in one cell
            f"{other_lat},{other_lon},330,1,1,2024-06-01,1600,N20,VIIRS,n,2.0NRT,290,12.0,D",
            f"{other_lat},{other_lon},330,1,1,2024-06-01,0400,N21,VIIRS,n,2.0NRT,290,8.0,D",
        ]
    )

    def getter(url: str):
        if "data_availability" in url:
            return 200, AVAILABILITY
        if "MODIS_" in url:
            return 200, body
        if "NOAA20" in url:
            return 200, HEADER + f"{other_lat},{other_lon},330,1,1,2024-06-01,1600,N20,VIIRS,n,2.0NRT,290,12.0,D\n"
        if "NOAA21" in url:
            return 200, HEADER + f"{other_lat},{other_lon},330,1,1,2024-06-01,0400,N21,VIIRS,n,2.0NRT,290,8.0,D\n"
        return 200, HEADER

    result = _client(tmp_path, getter).hotspots(
        -51, -15, -48, -12, "2024-06-01", ["Aqua", "NOAA-20", "NOAA-21"]
    )
    areas = result["hotspot_areas"]
    assert areas["detection_count"] == 12  # 10 Aqua + 1 NOAA-20 + 1 NOAA-21 after dedupe
    aqua_only = next(area for area in areas["areas"] if area["platforms"] == ["Aqua"])
    assert aqua_only["detection_count"] == 10
    assert aqua_only["satellite_count"] == 1
    assert aqua_only["multiple_satellites"] is False
    assert aqua_only["label"] == "area with detected heat"
    multi = next(area for area in areas["areas"] if area["multiple_satellites"])
    assert multi["satellite_count"] == 2
    times = {row["platform"]: row["observation_times_utc"] for row in multi["by_platform"]}
    assert times["NOAA-20"] == ["16:00"]
    assert times["NOAA-21"] == ["04:00"]
    assert "wildfire" not in result["public_result"]["text"].lower()
    assert result["public_result"]["area_count"] == areas["area_count"]


def test_clear_aqua_zero_keeps_the_viirs_point_and_counts_the_cell_once():
    from vela.contributions import cell_detail, present_scene

    viirs_point = {"platform": "Suomi-NPP", "lat": -15.0, "lon": -50.0, "source": "VIIRS_SNPP_SP"}
    scene = present_scene(
        [
            _observation(platform="Aqua", detected=False, visible_km2=20, hours_from_aqua=0.2, hotspot_pixel_count=0),
            _observation(
                platform="Suomi-NPP",
                detected=True,
                visible_km2=18,
                hours_from_aqua=0.5,
                hotspot_pixel_count=4,
                points=[viirs_point],
            ),
        ]
    )
    assert scene["map_points"] == [viirs_point]
    assert scene["cell_days"] == 1
    contribution = scene["contributions"][0]
    assert contribution["platform"] == "Aqua"
    assert contribution["detected"] is False
    detail = cell_detail(contribution)
    assert detail["supplied_by"] == "Aqua supplied this cell-day."
    assert detail["detected"] is False


def test_weekly_total_separates_coverage_from_activity_estimates():
    from vela.contributions import present_scene, tally_activity

    aqua_zero = _observation(
        platform="Aqua",
        detected=False,
        visible_km2=20,
        hours_from_aqua=0.1,
        hotspot_pixel_count=0,
        cell_id="aqua",
    )
    one = tally_activity(present_scene([aqua_zero])["contributions"])
    assert one["eligible_coverage_cell_days"] == 1
    assert one["activity_estimate_cell_days"] == 1
    assert one["activity_rate"] == 0
    assert one["activity_status"] == "complete"
    assert one["clear_zero"] is False

    week = tally_activity(present_scene([
        {**aqua_zero, "cell_id": f"aqua-{index}", "local_date": "2021-02-22"}
        for index in range(20)
    ])["contributions"])
    assert week["clear_zero"] is True
    assert week["activity_rate"] == 0

    suomi = _observation(
        platform="Suomi-NPP",
        detected=True,
        visible_km2=22,
        hours_from_aqua=0.4,
        hotspot_pixel_count=1,
        cell_id="shared",
        points=[{"platform": "Suomi-NPP", "lat": 1, "lon": 1}],
    )
    noaa = _observation(
        platform="NOAA-20",
        detected=True,
        visible_km2=13,
        hours_from_aqua=0.2,
        hotspot_pixel_count=9,
        cell_id="shared",
        points=[{"platform": "NOAA-20", "lat": 1.1, "lon": 1.1}],
    )
    fallback = present_scene([suomi, noaa])
    assert len(fallback["map_points"]) == 2
    assert len(fallback["contributions"]) == 1
    assert fallback["contributions"][0]["platform"] == "Suomi-NPP"
    counted = tally_activity(fallback["contributions"])
    assert fallback["contributions"][0]["method"] == "raw VIIRS activity"
    assert fallback["contributions"][0]["detected"] is True
    assert counted["eligible_coverage_cell_days"] == 1
    assert counted["activity_estimate_cell_days"] == 0
    assert counted["activity_rate"] is None
    assert counted["method_counts"]["raw VIIRS activity"] == 1
    assert counted["method_counts"]["calibrated VIIRS estimate"] == 0
    calibrated = tally_activity([{
        "platform": "Suomi-NPP",
        "method": "calibrated VIIRS estimate",
        "detected": True,
        "calibrated_value": 0.25,
        "visible_km2": 20,
    }])
    assert calibrated["activity_estimate_cell_days"] == 1
    assert calibrated["activity_rate"] == 0.25
    assert calibrated["method_counts"]["calibrated VIIRS estimate"] == 1

    pending = tally_activity(present_scene([
        _observation(platform="NOAA-21", detected=True, visible_km2=20, hotspot_pixel_count=4, cell_id="pending")
    ])["contributions"])
    assert pending["eligible_coverage_cell_days"] == 1
    assert pending["activity_estimate_cell_days"] == 0
    assert pending["activity_status"] == "unavailable"
    assert pending["activity_rate"] is None
    assert pending["clear_zero"] is False

    unknown = tally_activity(present_scene([
        _observation(platform="Suomi-NPP", eligible=False, detected=False, visible_km2=1, cell_id="unknown")
    ])["contributions"])
    assert unknown["eligible_coverage_cell_days"] == 0
    assert unknown["activity_estimate_cell_days"] == 0
    assert unknown["activity_status"] == "unavailable"
    assert unknown["clear_zero"] is False

    mixed = tally_activity(present_scene([
        aqua_zero,
        _observation(platform="NOAA-20", detected=True, visible_km2=18, cell_id="other-day", local_date="2021-02-23"),
    ])["contributions"])
    assert mixed["eligible_coverage_cell_days"] == 2
    assert mixed["activity_estimate_cell_days"] == 1
    assert mixed["activity_status"] == "partial"
    assert mixed["activity_denominator"] == 1
    assert mixed["activity_rate"] == 0


def test_real_suomi_fallback_ignores_the_hotter_pass():
    from pathlib import Path

    import pandas as pd

    from vela.contributions import cell_detail, contributions_for_rows

    excluded = Path("data/processed/excluded_cells.parquet")
    if not excluded.is_file():
        pytest.skip("development table is not on disk")
    frame = pd.read_parquet(excluded)
    rows = frame[
        (frame["cell_id"] == "523:-383") & (frame["local_date"].astype(str).str.slice(0, 10) == "2021-07-22")
    ].to_dict("records")
    scene = contributions_for_rows(rows)
    assert len(scene["contributions"]) == 1
    chosen = scene["contributions"][0]
    assert chosen["platform"] == "Suomi-NPP"
    assert chosen["rule"] == "viirs_coverage_and_time"
    assert chosen["aqua_ineligible_reason"] == "missing_modis"
    assert chosen["hotspot_pixel_count"] == 0
    assert chosen["visible_km2"] == pytest.approx(19.6875)
    detail = cell_detail(chosen)
    assert detail["supplied_by"] == "Suomi-NPP supplied this cell-day."
    assert detail["method"] == "raw VIIRS activity"
    assert detail["detected"] is False
    assert detail["raw_activity"] == 0
    assert detail["activity_estimate"] is None
    assert detail["hotspot_count_used"] is False
    hotter = max(int(row["viirs_hotspot_pixel_count"]) for row in rows)
    assert hotter == 1
    assert chosen["hotspot_pixel_count"] < hotter


def test_two_viirs_platforms_keep_both_points_and_count_the_cell_once():
    from vela.contributions import cell_detail, present_scene

    noaa20 = {"platform": "NOAA-20", "lat": -15.1, "lon": -50.1}
    noaa21 = {"platform": "NOAA-21", "lat": -15.2, "lon": -50.2}
    louder = _observation(
        platform="NOAA-20",
        detected=True,
        visible_km2=12,
        hours_from_aqua=0.2,
        hotspot_pixel_count=9,
        points=[noaa20],
    )
    quieter = _observation(
        platform="NOAA-21",
        detected=True,
        visible_km2=22,
        hours_from_aqua=1.1,
        hotspot_pixel_count=1,
        points=[noaa21],
    )
    scene = present_scene([louder, quieter])
    assert {point["platform"] for point in scene["map_points"]} == {"NOAA-20", "NOAA-21"}
    assert len(scene["map_points"]) == 2
    assert scene["cell_days"] == 1
    assert scene["contributions"][0]["platform"] == "NOAA-21"
    assert scene["contributions"][0]["harmonized_estimate"] == "calibration pending"
    swapped = present_scene(
        [
            {**louder, "hotspot_pixel_count": 1},
            {**quieter, "hotspot_pixel_count": 40},
        ]
    )
    assert swapped["contributions"][0]["platform"] == "NOAA-21"
    detail = cell_detail(scene["contributions"][0])
    assert detail["supplied_by"] == "NOAA-21 supplied this cell-day."
    assert "calibration pending" in detail["harmonized_estimate"]


def test_platform_transfer_plan_preserves_the_final_test_and_does_not_download():
    from vela.pairing import parse_granule_name
    from vela.platform_transfer import build_plan, transfer_year

    assert parse_granule_name("VJ114IMG.A2021053.1612.002.nc")["platform"] == "NOAA-20"
    assert parse_granule_name("VJ203IMG.A2025360.1200.002.nc")["platform"] == "NOAA-21"
    plan = build_plan()
    assert plan["harmonized_estimate"] == "calibration pending"
    assert plan["preserved_final_test_years"] == [2023, 2024]
    assert plan["frozen_suomi_npp"]["candidates_refit"] is False
    noaa21 = next(item for item in plan["pairs"] if item["viirs_platform"] == "NOAA-21")
    assert noaa21["evaluation_years"] == [2025, 2026]
    assert 2023 not in noaa21["evaluation_years"] and 2024 not in noaa21["evaluation_years"]
    assert transfer_year("NOAA-21", 2024) == "preserved_final_test"
    assert transfer_year("NOAA-21", 2022) == "before_firms_coverage"
    assert transfer_year("NOAA-21", 2025) == "platform-transfer"
    assert transfer_year("NOAA-20", 2021) == "platform-transfer"
    assert transfer_year("NOAA-20", 2023) == "preserved_final_test"


def test_noaa20_pilot_cannot_silently_activate_calibration_or_change_suomi_selection():
    from pathlib import Path

    from vela.contributions import CALIBRATION_PENDING_PLATFORMS, method_name

    assert "NOAA-20" in CALIBRATION_PENDING_PLATFORMS
    assert "NOAA-21" in CALIBRATION_PENDING_PLATFORMS
    assert method_name({"platform": "NOAA-20", "calibrated_value": 0.9}) == "unavailable"
    assert method_name({"platform": "NOAA-21"}) == "unavailable"
    selection = Path("data/models/model_selection.json")
    reserve = Path("data/models/reserve_inclusive_selection.json")
    if selection.is_file():
        payload = __import__("json").loads(selection.read_text(encoding="utf-8"))
        assert payload.get("chosen_model") == "random_forest"
    if reserve.is_file():
        payload = __import__("json").loads(reserve.read_text(encoding="utf-8"))
        assert payload.get("chosen_model") == "random_forest"
        assert payload.get("noaa20_calibration") == "calibration pending"
        assert payload.get("noaa21_calibration") == "calibration pending"
        assert "2023-2024" in (payload.get("reserved_not_run") or [])
        assert "pantanal" in (payload.get("reserved_not_run") or [])
    pilot_script = Path("scripts/ingest_noaa20_pilot.py").read_text(encoding="utf-8")
    assert "calibration_activated\": False" in pilot_script or "calibration_activated=False" in pilot_script or '"calibration_activated": False' in pilot_script
    assert "compact_shards" not in pilot_script
    assert "--i-authorize-download" in pilot_script


def test_page_keeps_every_hotspot_marker_and_the_combined_summary():
    from pathlib import Path

    page = Path("app/static/index.html").read_text(encoding="utf-8")
    script = _page_scripts()
    assert "Combined observations" in page
    assert "flatMap((result) => result.hotspots || [])" in script
    assert "calibration pending" in script
    assert "supplied this cell-day" in script or "supplied_by" in script


def test_missing_product_does_not_pretend_the_area_was_clear(tmp_path):
    calls = []

    def getter(url: str):
        calls.append(url)
        if "data_availability" in url:
            return 200, AVAILABILITY
        raise AssertionError("area was called")

    result = _client(tmp_path, getter).hotspots(0, 0, 1, 1, "1999-01-01", ["Suomi-NPP"])
    assert result["results"][0]["status"] == "product_unavailable"
    assert result["results"][0]["coverage"] == "unknown"
    assert all("data_availability" in url for url in calls)


def test_request_failure_is_redacted_and_dateline_makes_two_calls(tmp_path):
    def getter(url: str):
        if "data_availability" in url:
            return 200, AVAILABILITY
        return 500, f"broken {url}"

    failed = _client(tmp_path, getter).hotspots(0, 0, 1, 1, "2019-08-20", ["NOAA-20"])
    assert failed["results"][0]["status"] == "request_failed"
    assert "SECRET-KEY-99" not in json.dumps(failed)

    calls = []

    def dated(url: str):
        calls.append(url)
        if "data_availability" in url:
            return 200, AVAILABILITY
        return 200, HEADER

    _client(tmp_path, dated).hotspots(170, -20, -170, -10, "2019-08-20", ["Suomi-NPP"])
    area_calls = [url for url in calls if "/api/area/" in url]
    assert len(area_calls) == 8
    assert all("/1/2019-08-20" in url for url in area_calls)
    boxes = [list(map(float, url.split("/")[-3].split(","))) for url in area_calls]
    assert min(box[0] for box in boxes) == -180
    assert max(box[2] for box in boxes) == 180
    assert all(0 < box[2] - box[0] <= 5 and box[3] - box[1] <= 5 for box in boxes)
    assert sum((box[2] - box[0]) * (box[3] - box[1]) for box in boxes) == 200


def test_oversized_area_is_not_sent(tmp_path):
    def getter(_url: str):
        raise AssertionError("NASA was called")

    result = _client(tmp_path, getter).hotspots(-120, -40, 20, 40, "2019-08-20", ["Aqua"])
    assert result["results"][0]["status"] == "area_too_large"


def test_training_refuses_a_table_that_is_not_nasa_data(tmp_path, monkeypatch):
    pandas = pytest.importorskip("pandas")
    from vela.train import run_training

    def fake_data_dir(*parts):
        path = tmp_path.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("vela.train.data_dir", fake_data_dir)
    table = tmp_path / "paired_cells.parquet"
    pandas.DataFrame(
        [
            {
                "data_origin": "synthetic",
                "role": "train",
                "region_id": "cerrado",
                "local_date": "2019-08-20",
                "local_hour": 13.5,
                "center_lat": -14.0,
                "center_lon": -50.0,
                "modis_detected": True,
                "viirs_hotspot_pixel_count": 1,
                "shared_coverage_fraction": 0.8,
                **{f"viirs_{name}": 0 for name in ("fire_low", "fire_nominal", "fire_high", "clear", "cloud", "water", "unknown", "missing")},
            }
        ]
    ).to_parquet(table, index=False)
    report = run_training(table)
    assert report["chosen_model"] is None
    assert report["temporal_test"] is None
    assert any("not marked as NASA" in gap for gap in report["gaps"])


def test_training_reports_the_missing_years_regions_and_positives(tmp_path, monkeypatch):
    pandas = pytest.importorskip("pandas")
    from vela.masks import CATEGORIES
    from vela.train import run_training

    def fake_data_dir(*parts):
        path = tmp_path.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("vela.train.data_dir", fake_data_dir)
    rows = []
    for detected, region, role in ((True, "cerrado", "train"), (False, "pantanal", "transfer")):
        row = {name: 0 for name in (f"viirs_{item}" for item in CATEGORIES)}
        row.update(
            {
                "data_origin": "nasa",
                "role": role,
                "region_id": region,
                "local_date": "2019-08-20",
                "local_hour": 13.5,
                "center_lat": -14.0,
                "center_lon": -50.0,
                "modis_detected": detected,
                "viirs_hotspot_pixel_count": 1 if detected else 0,
                "shared_coverage_fraction": 0.8,
                "viirs_clear": 20,
                "viirs_fire_high": 1 if detected else 0,
            }
        )
        rows.append(row)
    table = tmp_path / "paired_cells.parquet"
    pandas.DataFrame(rows).to_parquet(table, index=False)
    report = run_training(table)
    text = " ".join(report["gaps"])
    assert report["chosen_model"] is None
    assert report["counts"]["train_rows"] == 1
    assert report["counts"]["transfer_rows"] == 1
    assert "Training positives are 1" in text
    assert "at least 3" in text
    assert "at least 2" in text
    assert "at least 4" in text
    assert not (tmp_path / "models" / "vela_model.joblib").exists()


def test_candidate_models_fit_on_training_rows_and_leave_validation_pending(tmp_path, monkeypatch):
    pandas = pytest.importorskip("pandas")
    from vela.masks import CATEGORIES
    from vela.train import fit_candidates

    def fake_data_dir(*parts):
        path = tmp_path.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    monkeypatch.setattr("vela.train.data_dir", fake_data_dir)
    rows = []
    for year, region in ((2013, "cerrado"), (2014, "california"), (2017, "cerrado")):
        for index in range(12):
            row = {f"viirs_{name}": 0 for name in CATEGORIES}
            row.update(
                {
                    "data_origin": "nasa",
                    "role": "train",
                    "region_id": region,
                    "local_date": f"{year}-06-15",
                    "local_hour": 13.0,
                    "center_lat": -14.0,
                    "center_lon": -50.0,
                    "modis_detected": index < 10,
                    "viirs_hotspot_pixel_count": 1 if index < 10 else 0,
                    "shared_coverage_fraction": 0.8,
                    "viirs_clear": 20,
                    "viirs_fire_high": 1 if index < 10 else 0,
                }
            )
            rows.append(row)
    held_out = {f"viirs_{name}": 0 for name in CATEGORIES}
    held_out.update(
        {
            "data_origin": "nasa",
            "role": "transfer",
            "region_id": "pantanal",
            "local_date": "2024-08-01",
            "local_hour": 13.0,
            "center_lat": -18.0,
            "center_lon": -56.0,
            "modis_detected": True,
            "viirs_hotspot_pixel_count": 4,
            "shared_coverage_fraction": 0.9,
            "viirs_clear": 10,
            "viirs_fire_high": 4,
        }
    )
    rows.append(held_out)
    table = tmp_path / "paired_cells.parquet"
    pandas.DataFrame(rows).to_parquet(table, index=False)
    report = fit_candidates(table)
    assert report["gaps"] == []
    assert report["chosen_model"] is None
    assert report["validation"] == "pending"
    assert report["temporal_test"] is None
    assert report["counts"]["train_rows"] == 36
    assert report["counts"]["train_positives"] == 30
    assert report["counts"]["transfer_rows"] == 1
    assert report["counts"]["test_rows"] == 0
    assert (tmp_path / "models" / "candidate_logistic_regression.joblib").is_file()
    assert (tmp_path / "models" / "candidate_random_forest.joblib").is_file()
    assert not (tmp_path / "models" / "vela_model.joblib").exists()


def test_synthetic_swaths_open_and_do_not_become_a_nasa_result(tmp_path):
    pytest.importorskip("pyhdf")
    pytest.importorskip("netCDF4")
    from pyhdf.SD import SD, SDC

    import netCDF4

    from vela.pipeline import process_directory
    from vela.readers import fire_histogram

    modis_shape = (4, 5)
    viirs_shape = (10, 10)
    modis_fire = tmp_path / "MYD14.A2019232.1730.061.synthetic.hdf"
    modis_geo = tmp_path / "MYD03.A2019232.1730.061.synthetic.hdf"
    viirs_fire = tmp_path / "VNP14IMG.A2019232.1740.002.synthetic.nc"
    viirs_geo = tmp_path / "VNP03IMG.A2019232.1740.002.synthetic.nc"

    fire = np.full(modis_shape, 5, dtype=np.uint8)
    fire[0, 0] = 9
    _write_hdf(modis_fire, {"fire mask": fire})
    latitudes = np.full(modis_shape, -14.0, dtype=np.float32)
    longitudes = np.full(modis_shape, -50.0, dtype=np.float32)
    _write_hdf(modis_geo, {"Latitude": latitudes, "Longitude": longitudes})

    viirs_mask = np.full(viirs_shape, 5, dtype=np.uint8)
    viirs_mask[0, 0] = 9
    _write_netcdf(viirs_fire, "fire mask", viirs_mask)
    _write_netcdf(viirs_geo, "latitude", np.full(viirs_shape, -14.0, dtype=np.float32), "longitude", np.full(viirs_shape, -50.0, dtype=np.float32))

    modis_check = fire_histogram(modis_fire)
    viirs_check = fire_histogram(viirs_fire)
    assert modis_check["format"] == "HDF4"
    assert viirs_check["format"] == "NetCDF4/HDF5"
    assert modis_check["pixels"] == 20
    assert viirs_check["pixels"] == 100
    assert "synthetic" in modis_check["file_name"]

    region = {
        "id": "synthetic-landscape",
        "name": "Synthetic landscape",
        "landscape": "fixture",
        "role": "train",
        "west": -52.5,
        "south": -15.5,
        "east": -48.5,
        "north": -12.5,
    }
    result = process_directory(
        [str(modis_fire), str(modis_geo), str(viirs_fire), str(viirs_geo)],
        (region["west"], region["south"], region["east"], region["north"]),
        region,
        settings(),
    )
    assert result["eligible"]
    assert {row["data_origin"] for row in result["eligible"]} == {"synthetic"}
    assert result["eligible"][0]["outcome"] == "both"
    assert result["confirmed_passes"][0]["modis_shape"] == [4, 5]
    assert result["confirmed_passes"][0]["viirs_shape"] == [10, 10]


def _write_hdf(path, arrays):
    from pyhdf.SD import SD, SDC

    types = {np.dtype("uint8"): SDC.UINT8, np.dtype("float32"): SDC.FLOAT32}
    dataset = SD(str(path), SDC.WRITE | SDC.CREATE)
    try:
        for name, values in arrays.items():
            array = np.asarray(values)
            variable = dataset.create(name, types[array.dtype], array.shape)
            variable[:] = array
            variable.endaccess()
    finally:
        dataset.end()


def _write_netcdf(path, *pairs):
    import netCDF4

    dataset = netCDF4.Dataset(path, "w")
    try:
        sample = np.asarray(pairs[1])
        dataset.createDimension("y", sample.shape[0])
        dataset.createDimension("x", sample.shape[1])
        for index in range(0, len(pairs), 2):
            name = pairs[index]
            values = np.asarray(pairs[index + 1])
            variable = dataset.createVariable(name, "f4" if values.dtype.kind == "f" else "u1", ("y", "x"))
            variable[:] = values
    finally:
        dataset.close()


def test_app_shell_loads_without_a_map_key():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from app import main

    original = main.FIRMS.key
    main.FIRMS.key = ""
    try:
        client = TestClient(main.app)
        page = client.get("/")
        assert page.status_code == 200
        assert "The Fire Time Machine" in page.text
        response = client.post(
            "/api/hotspots",
            json={"west": 0, "south": 0, "east": 1, "north": 1, "date": "2019-08-20", "platforms": ["Aqua"]},
        )
        body = response.json()
        assert body["results"][0]["status"] == "not_configured"
        assert "/api/area/" not in response.text
        assert "not shown here" in response.text
    finally:
        main.FIRMS.key = original


def test_insufficient_coverage_states_its_reason_and_the_batch_stays_three_weeks():
    from scripts.ingest_validation_batch import SELECTED_WEEKS
    from vela.calendar_metrics import insufficient_reason

    config = {"min_usable_cell_days_per_week": 20, "min_shared_coverage": 0.5}
    assert insufficient_reason(
        {"coverage_status": "ok", "usable_cell_days": 20, "mean_shared_coverage": 0.8},
        config,
    ) is None
    assert "No eligible cell-days" in insufficient_reason(
        {"coverage_status": "insufficient", "usable_cell_days": 0, "mean_shared_coverage": None},
        config,
    )
    text = insufficient_reason(
        {"coverage_status": "insufficient", "usable_cell_days": 8, "mean_shared_coverage": 0.2},
        config,
    )
    assert "at least 20" in text
    assert "at least 0.5" in text
    assert [row["region_id"] for row in SELECTED_WEEKS] == ["cerrado", "california", "zambia"]


def test_validation_budget_stops_before_the_week_that_exceeds_it():
    from vela.expansion import choose_validation_budget

    weeks = [
        {"region_id": "cerrado", "week_start": "2021-02-22", "candidate_daytime_passes": 7, "matched_pass_bytes": 100},
        {"region_id": "california", "week_start": "2021-03-22", "candidate_daytime_passes": 9, "matched_pass_bytes": 100},
        {"region_id": "yakutia", "week_start": "2021-11-22", "candidate_daytime_passes": 14, "matched_pass_bytes": 250},
        {"region_id": "arnhem", "week_start": "2022-11-28", "candidate_daytime_passes": 6, "matched_pass_bytes": 40},
    ]
    chosen = choose_validation_budget(weeks, budget_bytes=250)
    assert [row["region_id"] for row in chosen["weeks"]] == ["cerrado", "california"]
    assert chosen["stopped_before"]["region_id"] == "yakutia"
    assert chosen["unique_new_bytes"] == 200
    assert chosen["fire_counts_used"] is False


def test_frozen_selection_scores_the_same_weeks_and_leaves_the_final_test_alone():
    pandas = pytest.importorskip("pandas")
    import numpy as np

    from vela.masks import CATEGORIES
    from vela.settings import settings
    from vela.train import score_frozen_pipelines, selection_frame
    from vela.train import _prepare

    class Constant:
        def predict_proba(self, frame):
            probability = np.full(len(frame), 0.25)
            return np.column_stack([1 - probability, probability])

    def cell(region, day, role, detected):
        row = {f"viirs_{name}": 0 for name in CATEGORIES}
        row.update(
            {
                "data_origin": "nasa",
                "role": role,
                "region_id": region,
                "local_date": day,
                "local_hour": 13.0,
                "center_lat": -14.0,
                "center_lon": -50.0,
                "modis_detected": detected,
                "viirs_hotspot_pixel_count": 1 if detected else 0,
                "shared_coverage_fraction": 0.8,
                "viirs_clear": 20,
                "viirs_fire_high": 1 if detected else 0,
            }
        )
        return row

    rows = [cell("cerrado", "2021-06-16", "train", False) for _ in range(20)]
    rows.extend(cell("zambia", "2021-07-21", "train", True) for _ in range(20))
    rows.extend(cell("cerrado", "2021-08-04", "train", False) for _ in range(5))
    rows.append(cell("pantanal", "2021-06-16", "transfer", True))
    rows.append(cell("cerrado", "2024-06-12", "train", True))
    prepared = _prepare(pandas.DataFrame(rows), settings())
    tune = selection_frame(prepared)
    assert set(tune["region_id"]) == {"cerrado", "zambia"}
    assert set(tune["iso_year"]) == {2021}
    scored = score_frozen_pipelines(
        prepared,
        {"raw_viirs": None, "logistic_regression": Constant(), "random_forest": Constant()},
        ["cerrado"],
        settings(),
    )
    by_week = {row["week_start"]: row for row in scored["weeks"]}
    quiet = by_week["2021-06-14"]
    active = by_week["2021-07-19"]
    thin = by_week["2021-08-02"]
    assert quiet["scored"] is True
    assert quiet["observed_modis_rate"] == 0
    assert quiet["usable_cell_days"] == 20
    assert quiet["estimates"]["raw_viirs"] == 0
    assert quiet["absolute_error_percentage_points"]["raw_viirs"] == 0
    assert active["region_group"] == "new"
    assert active["estimates"]["raw_viirs"] == 1
    assert active["absolute_error_percentage_points"]["logistic_regression"] == 75
    assert thin["scored"] is False
    assert thin["observed_modis_rate"] is None
    assert scored["weekly_mae_percentage_points"]["raw_viirs"] == 0
    assert scored["weekly_mae_percentage_points"]["logistic_regression"] == 50
    assert scored["weekly_mae_by_region_group"]["previously_trained"]["raw_viirs"] == 0
    assert scored["weekly_mae_by_region_group"]["new"]["logistic_regression"] == 75
    assert scored["chosen_model"] is None
    assert scored["final_test_evaluated"] is False
    selected = score_frozen_pipelines(
        prepared,
        {"raw_viirs": None, "logistic_regression": Constant(), "random_forest": Constant()},
        ["cerrado"],
        {**settings(), "min_tune_weeks": 2},
    )
    assert selected["chosen_model"] == "raw_viirs"
    assert selected["temporal_test"] is None
