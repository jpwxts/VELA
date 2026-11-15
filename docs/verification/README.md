# Public evidence audit — 15 November 2026 (Asia/Manila)

**Historical audit:** the numerical reproduction and calibration findings below remain valid. The later user-authorized national experimental path, its separate fallback evaluation, and current UI supersede the publication-suspension behavior described here. See [national-prediction.md](national-prediction.md).

Base independently fetched from GitHub: `dc73925f16ff460d33f65712ee2834be4307e442` on `main`. Local tracked files initially matched; the user's untracked `Untitled` was left alone. No training or holdout artifacts were replaced. OmniRoute's local README identifies an AI gateway; it supplies no satellite observations or fire-mask coverage and was not integrated.

## Trace and root cause

| Quantity | Serving path | Source, scope and time | Artifact/cache |
| --- | --- | --- | --- |
| Fire-weather danger | `/api/preparedness`; compatibility `/api/check-land` | Current Open-Meteo point outlook and Copernicus GWIS ECMWF FWI/ranking near bbox center; ~8 km GWIS grid; each day has its own valid date. A historical heat date does not make this historical weather. | Published GWIS thresholds, no hotspot classifier. `data/preparedness/forecasts.sqlite`; new provider cache `data/cache/weather.sqlite`, <=1h and UTC date keyed. |
| Satellite heat | `/api/check-land` (`include_weather:false`), `/api/observation-ask`, `/api/hotspots` | NASA FIRMS point readings, clipped by coordinates; Philippine checks combine overlapping UTC days and filter acquisition times to Asia/Manila. Direct `/api/hotspots` retains its UTC-day API contract. | No ML artifact. `data/cache/firms.sqlite` and `data/observations/philippines.sqlite`; store-seeded records keep acquisition times. Per-feed failures remain distinct from returned points. |
| Estimated burning activity | `/api/history/month`; land check now uses the same polygon/day contribution calculation | Eligible Aqua observation or calibrated Suomi-NPP cell-days. Numerator = sum of activity contributions; denominator = contributing eligible square-days. Missing coverage is a gap. | Frozen harmonization model `data/models/vela_model.joblib` and `model_selection.json`, processed paired tables; eligible activity store rows. NOAA-20/21 readings alone cannot supply harmonized activity. |
| Next-24-hour satellite heat forecast | `/api/hotspot-forecast`, `/month`, `/overlay`, `/polygon-summary`, `/replay` | Compact Maguindanao research region only; target window `[00:00 PH, next 00:00 PH)`. No land-wide probability. **Public percentages suspended.** | Candidate HGB hash `3c1e4896964db152`; policy `philippines_hotspot_selection.json`; research archive `philippines_hotspot_forecasts.sqlite`. Public requests now only read timely, matching, approved archive rows. |
| Saved example | `/api/public/philippines/2026-11-07?region=mindanao` | Checked-in NASA FIRMS **UTC-day** snapshot, not a new NASA query | `data/public/philippines/2026-11-07.geojson` |

The first old `No estimate yet` cause is `model_for_drawn_area`: no matching published weekly row from `build_calendar` for the bbox/date. The UI then discarded that explanation. `paired_cells.parquet` has 41,456 rows dated 2013–2022; no 2026-11-07 records. The separate Philippine hotspot coverage parquet has 11,437 rows, ending 2024-03-13, also none on 2026-11-07. The operational activity store has no 2026-11-07 contributions. This is missing eligible operational coverage/contributions, not evidence of zero burning. The old weekly-only land path also differed from History's daily store path. Land/square summaries now use History's polygon/day calculation. Broad `mindanao_coverage_firms_backfill_v1` rows are excluded from public harmonization: arbitrary MODIS/VIIRS coverage and a FIRMS point are not themselves an Aqua observation or calibrated Suomi estimate.

See [nov7-audit.json](nov7-audit.json) for actual records, features and artifact scores.

## Numerical reproduction

| Cell | Recorded displayed score | Model/hash | Created (UTC), despite nominal 7 Nov issue slot |
| --- | --- | --- | --- |
| `2393:174` | 0.010489014985782181 → **1%** | v1 Extra Trees / `b299a230f29f8c39` | 2026-11-14 13:43:56.482142 |
| `2397:180` | 0.9948734278161007 → **99%** | v2.1 HGB / `3c1e4896964db152` | 2026-11-14 15:57:43.979847 |

Both snapshot readings are NOAA-21, **7 Nov 12:33 PH / 04:33 UTC**. Cell 2393:174: `(6.85779,124.05852)`, FRP 13.89; cell 2397:180: `(7.08782,124.25303)`, FRP 8.93. Those readings occur *after* the nominal midnight feature cutoff. They are outcomes, not issue-time predictors.

Both stored feature rows have zero local 1/3/7-day heat counts, zero local distinct satellites in 7 days, and the same November sine/cosine. Differences: neighbor heat over 3 days **0 vs 1**, hours since local heat **14746.5 vs 23362.4333**, coverage-days feature **6 vs 0**. The same regional recent-detection proxy gives 11.1167 hours for the field named `hours_since_last_usable_pass`.

Recovered the actual v1 joblib from Git object `11f1861:data/models/philippines_hotspot_winner.joblib`; hash matches the archived v1 issue. Re-scoring its stored inputs reproduces **0.010489014985782181 exactly**. That old model gives the other cell **0.01460449570634722**. The current HGB artifact gives the old 1% cell **0.9934357854707622** using those same stored inputs, and reproduces the 99% cell exactly. This is primarily a mixed-generation serving problem, not a difference explainable by "one NOAA-21 reading".

Both archive records were created seven days after their target windows. They are not prospective forecasts, regardless of their old `historical_simulation:false` flags. Public serving now checks creation time against window start, candidate hash/version, geography and approval; requests cannot create new retrospective forecasts or delete old research issues.

## Scientific audit and promotion policy

No retraining was performed. More representative coverage and a newly preregistered split are required before fitting/calibrating another candidate. Existing six-classifier comparisons and seasonal/persistence baselines remain intact.

* v1 wrongly inferred **62,749 negatives** from successful/empty regional FIRMS searches. Its original report is preserved as `philippines_hotspot_model_comparison_v1_flawed_negatives.json`.
* v2.1 has **1,187 positives, 2,211 negatives, 60,970 unknown** considered square-days. A negative requires measured usable fire-mask/geolocation coverage (>=50% visible land) and zero qualifying detections. Positive FIRMS labels come from a much wider range of dates than covered negatives.
* Frozen split: train **589 (119+/470−)**, validation **1,001 (415+/586−)**, test **1,808 (653+/1,155−)**. Even-index earlier cells supply training through 2023 and validation in early 2024; odd-index cells or dates >=2024-08-01 supply test. Some cells overlap by time; this is not an entirely disjoint geography/time holdout. Episode restrictions and training-only imputation/scaling are implemented.
* Six candidates: logistic, decision tree, random forest, Extra Trees, histogram gradient boosting, calibrated SVM. HGB selected by validation Brier **0.2600078**, ahead of Extra Trees **0.2641763** and seasonal baseline **0.3298706**. SVM calibration is not calibration of HGB. Winner selection does not establish reliable probabilities.
* Claimable existing holdout excluding the v2.2 reserve: **524**, **218 positives**, Brier **0.225467**, PR-AUC **0.679798**, recall **0.775229** (threshold 0.1). Original reports already include additional reserve results; they are not a fresh untouched evaluation and were not used here to tune or promote anything.
* Existing high-band audit on those 524 rows: **32 predictions >=90%, mean 99.0967%, 32 positives**. All are August rows from positive-only seasonal strata. Later-date audit has **140 positives and no negatives**. These cannot validate high November probabilities.
* Existing broader 1,808-row holdout reliability (includes rows excluded from the 524 claimable set):

| Probability band | n | Mean prediction | Observed fraction |
| --- | ---: | ---: | ---: |
| 0–10% | 787 | 4.94% | 20.33% |
| 10–20% | 220 | 15.60% | 22.73% |
| 20–30% | 187 | 24.49% | 37.43% |
| 30–50% | 259 | 39.29% | 45.56% |
| 50–70% | 165 | 59.37% | 53.33% |
| 70–100% | 190 | 91.39% | 87.89% |

Feature audit found two additional limitations: `hours_since_last_usable_pass` is actually time since a recent detection **anywhere in the study**, not a measured clear pass in that cell. `coverage_days_7d` uses a regional set of coverage dates, not cell-specific keys. Historical publication times are unavailable (acquisition≈availability assumed). Existing 500-row delay sensitivity reports 0% changed at 6h and 10% at 24h; it is not a deployment latency validation. These definitions must be corrected in a versioned dataset before a new frozen comparison, not silently changed underneath the existing artifact. Training months are February/March plus sparse August; November is outside that support.

The selected research candidate remains versioned; `approved_for_serving:false` and `calibration_verified:false` explicitly suspend public publication. Research metrics remain visible. No square displays a competing classifier's probability; no map/land aggregate is a wildfire probability.

## Snapshot and Philippine-day reconciliation

Saved Mindanao snapshot: **12 readings / 11 squares / 3 satellites** (NOAA-21 6, NOAA-20 5, Terra 1). It is the 7 Nov **UTC** file. **11 readings are on 7 Nov PH; 1 NOAA-21 reading is on 8 Nov PH at 01:11.** Latest snapshot pass is `2026-11-08T01:11:00+08:00`. The file cannot supply a complete Philippine day because it omits the previous UTC evening. The saved example keeps all 12 and explicitly labels the UTC scope; History groups available observations by Philippine day. Saved snapshot totals are no longer entered as a 12-reading Philippine-day check in browser session history.

Small plot used for API reproduction: west/south/east/north `(123.95727,6.78538,124.10909,6.92485)`, enclosing cell 2393:174. The second disputed cell is outside that plot and is checked separately within All Mindanao.

## Timing and verification limits

See the JSON timing files. Each series has **three samples**, first call process-cold with existing disk/store caches retained, next two warm. Percentiles are interpolated sample statistics, not production p95 estimates. No provider caches were cleared, so these are not cache-cold measurements. TestClient measures API completion, not browser paint.

`before-timings.json`: measured on unchanged main before edits, in the restricted process. NASA requests failed; local stored readings still returned. `after-timings.json`: same restricted environment, after the changes. These primarily measure failure handling. Do not compare their weather failure latency to successful provider performance.

`after-network-timings.json`: explicit network-enabled run; FIRMS area requests returned HTTP 200. Heat-only land first call **6625.56 ms**, warm **96.90 / 80.14 ms** (warm median **88.52 ms**); sample p50/p95 **96.90 / 5972.69 ms**. Weather still took about **8.3 s** on its independent endpoint. Full values and FIRMS internal elapsed times are in the file. There is no matched successful network-enabled pre-change baseline, so no claim of a measured live speedup or reproduction of the earlier "18 seconds" report.

Heat now starts its own request (`include_weather:false`), with 45s client cancellation; independent weather has a 25s client timeout. FIRMS provider attempts are bounded at 12s, one attempt. Weather provider reads are bounded at 8s, one attempt, with seven day workers instead of serial daily GWIS reads. Successful weather responses are cached <=1h keyed by URL/parameters and UTC day; lock stripes deduplicate simultaneous identical requests. Failed weather reads are not cached. FIRMS retains its dated product/tile cache and store seed. Month/square responses have scope and request guards; repeated pending square/month reads are deduplicated. Changing selection aborts the prior land request. Coverage requests have independent errors and a 15s browser timeout.

Validation performed:

* Running FastAPI APIs and saved snapshot: both cells, All Mindanao, small plot, unsupported square, future date, zero-return vs failed-feed distinction, suppressed archived forecasts, no full-month reconstruction, and consistent Philippine-day square checks.
* Python suite and Node unit tests (see final execution report). Node tests execute the actual chart selector and land request code with controlled async responses: heat paints while weather is unresolved and obsolete weather cannot overwrite a newer request. They are **not** browser tests.
* JavaScript syntax checks and `git diff --check`.

**Real-browser verification was blocked.** Chrome inventory was available, but acquiring/creating a tab failed inside the browser-control bridge (`timeoutMs` error). Native Chrome fallback then timed out and its app server exited. Neither a screenshot nor the fresh-load → draw → click → month → charts → Live flow was verified. No browser-paint timings, screenshot evidence, successful live weather result, or visual layout validation are claimed. Manual browser review is still required before calling the UI release verified.

### Restricted-process before/after sample table (milliseconds)

External requests failed in these runs. n=3, warm=last two; existing caches retained. These are not live success latency comparisons.

| API | Before first | Before warm median | Before p50 / p95 | After first | After warm median | After p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| land | 3248.80 | 937.54 | 965.85 / 3020.51 | 1228.52 | 955.11 | 1033.71 / 1209.04 |
| weather | 771.73 | 779.53 | 778.05 / 780.71 | 11.02 | 8.20 | 8.31 / 10.75 |
| forecast | 1277.79 | 139.21 | 139.39 / 1163.95 | 1192.65 | 2.71 | 3.23 / 1073.71 |
| history | 93.47 | 51.16 | 60.28 / 90.15 | 90.91 | 98.44 | 92.44 / 103.23 |
| chart | 51.22 | 55.64 | 51.22 / 61.17 | 2069.38 | 115.97 | 163.20 / 1878.76 |

FIRMS internal elapsed: before final sample **778 ms**; network-enabled after samples **6300 / 5 / 5 ms**. The new daily chart uses History; `chart` in this benchmark denotes the retained legacy `/api/calendar` API. Its cold cost increased in these samples, so no across-the-board speedup is claimed. The primary verified improvement is removing the weather dependency from heat rendering.

### Final running-server checks

The updated server on `127.0.0.1:8001` returned HTTP 200 for the page and the three-choice chart control. Both named square endpoints return null percentages with calibration reasons; cell `2100:200` returns unsupported. `running-http-checks.json` records full returned data. A NASA-backed 7 Nov Philippine-day check using the same Mindanao display outline as the UI returned **11 readings / 10 squares** in **6680.59 ms** (one sample). The small Maguindanao plot returned **2 readings / 2 squares** (one NOAA-20, one NOAA-21) in **69.93 ms** with existing caches. Its Aqua search returned no points, Suomi-NPP was unavailable, and clear-view coverage remained unknown. This is a different query window/feed set from the **12 / 11** saved UTC snapshot; the counts must not be asserted equal.

Final checks: **154 Python tests passed, 1 skipped**, with one existing netCDF/NumPy binary-compatibility warning; **3 Node tests passed**. JavaScript syntax checks and `git diff --check` passed. The final Node tests also check duplicate square-month suppression and rejection of obsolete responses after switching/reselecting months. Browser-control retry again failed. The work is suitable for code review, but the requested real-browser acceptance flow remains outstanding.

Full preset follow-up: `boundary_preset:mindanao` now carries the actual multipolygon through land checks and History, even though the map draws one outline. The full Philippine-day preset returned **11 readings / 10 squares** in **6555.89 ms** (one network-enabled sample); 17 points in the padded query were clipped to the named region. A regression test checks that History receives the same multipolygon. Selection, date, feed details and Return to Live controls are kept accessible after selecting land or a square.
