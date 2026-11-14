# Vela — Check my land

**Vela** is a map-first web app for the [NASA Space Apps](https://www.spaceappschallenge.org/) challenge *Harmonization of MODIS and VIIRS Hot Spots*.

You draw or search for a plot of land, pick a date, and explore four questions in one panel—without leaving the map:

| Tab | Question it answers |
| --- | --- |
| **Burn activity** | What heat did the satellites see on this land, grouped in 5 km squares? |
| **Weather outlook** | Which day has the highest fire danger near this land, and why? |
| **History** | How did burning activity change across a month or year on this land? |
| **Research** | How did Vela reach this result? |

Vela keeps **satellite heat**, **fire-danger weather**, **weekly activity estimates**, and **official wildfire reports** as separate answers. It never turns FWI, hotspot counts, MODIS confidence, or the harmonization model into a wildfire probability.

### Live is the default (Philippines)

The map opens in **Live**. Drawing land in Mindanao or elsewhere in the Philippines automatically uses today’s **Asia/Manila** calendar day (`GET /api/live/today`). Modes:

| Mode | What it does |
| --- | --- |
| **Live** | Philippine today · FIRMS feeds · writes `data/observations/philippines.sqlite` |
| **History** | Opens the monthly calendar/chart for the selection |
| **Saved example** | November 7 2026 public snapshot (does **not** change Live’s today) |

Controls: **Refresh now** (national FIRMS refresh into the store) and **Return to live**.

**Background refresh (browser-independent):**

```bash
conda activate vela
python -m scripts.refresh_philippines_firms --loop --interval-minutes 30
```

Requires `FIRMS_MAP_KEY` in `.env`. Persistent store: `data/observations/philippines.sqlite` (shared by worker and web). At Philippine midnight, Live advances because refresh always queries `philippine_today()`.

**Timestamps shown separately:** latest satellite observation · last successful source check · estimates processed through.

### Draw-land activity formula

When eligible inputs exist for the drawn boundary:

```text
Activity (%) = 100 × (sum of Aqua activity indicators + sum of eligible calibrated fallback probabilities)
             ÷ (number of square-days with valid contributions)
```

- Aqua contributes an observed 0 or 1 (clear zeros stay zeros).
- Eligible Suomi-NPP contributes its frozen random-forest probability when required inputs exist.
- Calibration-pending NOAA-20/21 readings stay visible as raw evidence and do not enter the total.
- Each contributing square-day counts once. Partial coverage is labeled partial and uses only the estimated denominator.
- When the denominator is zero, Vela explains the missing input and still shows weather + satellite findings.

**Development validation (not Philippines):** weekly activity-share mean absolute error is **0.66 percentage points** across four development weeks.

**Philippine evaluation (“Agreement with Aqua in the Philippines”):** run `python -m scripts.evaluate_philippines_agreement`. Current result: **0 Philippine paired cell-days** in `paired_cells.parquet`, so weekly MAE and Brier score are **undefined**. Smallest archive candidate set remains the a-priori 2019-03-06 Mindanao quartet (**170 243 619 B**, not downloaded). See `data/metrics/philippines_agreement_with_aqua.json`. Wildfire confirmation is a separate evaluation.

### Philippine satellite-hotspot forecast (MODIS/VIIRS, Mindanao-wide)

Public question: *For this 5 km square, what is the estimated chance that MODIS or VIIRS will detect heat in the next 24 hours?*  
Label shown in the UI: **Chance satellites record a hotspot in this square.**

This product is **separate** from Aqua–Suomi harmonization and from the Philippine wildfire-onset research pipeline. It uses **NASA MODIS/VIIRS only** (no BFP, no weather APIs). It is **not** a wildfire-onset probability.

| Piece | Location |
| --- | --- |
| Daily coverage rule (v2.1) | `data/metrics/philippines_hotspot_coverage_rules.json` |
| Granule CMR inventory | `data/metrics/philippines_hotspot_granule_inventory.json` |
| Pilot trace | `data/metrics/philippines_hotspot_coverage_pilot_trace.json` |
| Coverage cell-days | `data/processed/philippines_hotspot_coverage_cell_days.parquet` |
| Training cell-days | `data/processed/philippines_hotspot_cell_days.parquet` |
| Split + counts | `data/manifests/philippines_hotspot_split.json` |
| v2.1 comparison | `data/metrics/philippines_hotspot_model_comparison.json` |
| Count reconciliation | `data/metrics/philippines_hotspot_count_reconciliation.json` |
| Generalization audit | `data/metrics/philippines_hotspot_generalization_audit.json` |
| High-% audit | `data/metrics/philippines_hotspot_high_probability_audit.json` |
| Tamatalon 99% diagnosis | `data/metrics/philippines_hotspot_tamatalon_99pct_diagnosis.json` |
| Sealed v2.2 reserve | `data/manifests/philippines_hotspot_holdout_v2_2_reserve.json` |
| Multi-region registry | `data/manifests/mindanao_hotspot_regions_v1.json` |
| Supported-area map | `data/metrics/mindanao_hotspot_supported_areas.json` |
| Model board (6 + baselines) | `data/models/philippines_hotspot_models/` |
| Mindanao FIRMS 4h status | `data/metrics/mindanao_firms_refresh_status.json` |
| Flawed v1 archive | `data/metrics/philippines_hotspot_model_comparison_v1_flawed_negatives.json` |
| API | `GET /api/hotspot-forecast`, `/replay`, `/metrics`, `/month` |

**Eligibility (square, month, map, replay).** Study geography = all Mindanao land. **Percentages** only inside Maguindanao v2.1 evaluated box; other Mindanao cells → coverage/readings only; outside Mindanao → unsupported. Philippine issue date ≤ today (else **Upcoming**, no percent). Past/today responses include `model_board` (all classifiers + baselines) plus claimable holdout Acc/Brier as evaluation context — never as that day’s accuracy. Scores ≥90% or OOD months are labeled **experimental**. History never puts a forecast percent under “Month's activity.”

**4-hour Mindanao FIRMS.** `python -m scripts.refresh_mindanao_firms --once` or `--loop --interval-minutes 240`. Install: `scripts/install_mindanao_firms_refresh.sh`. Status stamp appears on metrics + square UI.

**Study / percentage zone.** Island study `117.97–126.74°E, 4.45–10.61°N` (clip `mindanao`). Percentage zone remains Maguindanao `123.6–124.7°E, 6.3–7.4°N` until island selection is promoted. FIRMS windows 2023–2026; fire-mask recovery prioritized on **2023–2024** dry-season Aqua MYD14/MYD03 pairs. March 2019 is **reader smoke-test only**.

**Daily coverage rule (v2.1).** Daytime fire+geo pass; visible land = clear or fire (≥50% of 25 km² = 12.5 km²). Cloud/water/unknown/glint/bow-tie/missing do not count. A no-detection pass with enough visible land supports “no heat at that observation time.” Daily **negative** = ≥1 such pass and zero FIRMS/fire-mask detections that Philippine day. Empty FIRMS search alone = **unknown**. The public percentage is the chance of ≥1 qualifying detection in the next 24 h (Manila midnight issue), scored on adequately observed square-days.

**First coverage-backed negative.** Cell **`2396:181`** · PH date **`2024-02-25`** · Aqua `2024-02-25T05:10:00Z` · granules `MYD14.A2024056.0510…` + `MYD03.A2024056.0510…` · visible land **13.0 km² (52%)** · detections **0** · label **negative**. Cloudy unknown demo: **`2389:173`** on **`2023-08-17`** (size-first pilot; 0 km² clear).

**CMR inventory (2023–2024 recover windows).** 259 daytime complete fire+geo pairs; estimated full daytime transfer ~25.9 GB (exceeds free disk) → Aqua-only dry-season batches (~27 MB/pair). Pilot chosen by size/opportunity before fire outcomes.

**Labels (revised counts).** positives **1187** · supported negatives **2211** · unknown **60970** · universe **64368** square-days (= v1 **63936** + **432** from Live-feed day **2026-10-01** × 432 study cells; that day is all-unknown). Scored rows train/val/test **589 / 1001 / 1808**. Independent eval = odd x-index cells **or** dates ≥ 2024-08-01 (previously inspected v1 holdout stays archived).

**v2.1 leaderboard (validation Brier).** HistGradientBoosting **0.260** (winner) · Extra Trees 0.264 · calibrated SVM 0.283 · logistic 0.296 · RF 0.301 · seasonal 0.330 · persistence 0.383 · tree 0.425.

**Claimable holdout (ex v2.2 reserve).** Brier **0.225** · P 0.515 · R 0.775 · F1 0.619 · PR-AUC 0.680 · n **524**. Full test including sealed reserve (audit only) Brier **0.199**. Cold squares: P 0.453 · R 0.714 · F1 0.554 · PR-AUC 0.654 · skill vs seasonal +0.168. Recent-heat: R 0.971 · PR-AUC 0.726 · skill +0.399.

**v2.2 sealed reserve.** Test-only rows with x≥2398 **or** issue months 2025-02/03 / 2026-11 (**1284** reserved / **524** claimable). Registered before further tuning; excluded from imputation, threshold, model selection, and promotion claims.

**Analytics.** Research tab shows v2.1 six-model board, high-% experimental limitations, and **“Archived experiment — coverage labels revised”** for the six v1 models. Preserved `2393:174` 1% replay keeps v1 `extra_trees` and distinguishes recorded creation time from the Manila midnight issue slot.

**Tamatalon calendar fix.** Cell `2399:175` on 2026-11-14 can still show a high Live % (OOD November seasonality; see diagnosis JSON) marked experimental; **15–30 Nov show Upcoming**, not issued percents. June contrast for the same sparse cell is ~3%.

```bash
conda activate vela
python -m scripts.refresh_mindanao_firms --once
python -m scripts.export_hotspot_model_board
python -m scripts.inventory_mindanao_hotspot_granules
python -m scripts.process_mindanao_hotspot_coverage --pilot
python -m scripts.build_hotspot_forecast_dataset
python -m scripts.train_hotspot_forecast
python -m scripts.backfill_mindanao_activity_from_coverage
python -m scripts.publish_mindanao_supported_areas
```

**Demo clicks.** Live → Maguindanao / Tamatalon → cell `2399:175` (past date shows multi-model board; Nov after today = Upcoming) · Bukidnon `2412:193` (coverage only) · place outside Mindanao (unsupported) · History forecast legend · Research → FIRMS refresh stamp + island selection pending.

**Geographic expansion.** See `mindanao_hotspot_regions_v1.json` / `mindanao_hotspot_supported_areas.json` — Bukidnon, Davao, Zamboanga, Caraga, Cotabato tiles; Maguindanao v2.1 selection is not overwritten; `mindanao_island_selection.json` stays blocked until promotion.

### Philippine 24-hour wildfire-onset forecast (Mindanao-first)

Product question (when labels exist): *What is the estimated probability that at least one new wildfire will start in this 5 km square during the next 24 hours?*

| Piece | Location |
| --- | --- |
| Label schemas + import | `vela/onset_labels.py`, `scripts/import_philippines_onset_labels.py` |
| Label audit | `data/metrics/philippines_onset_label_audit.json` |
| BFP-669031036800 investigation | `data/metrics/bfp_669031036800_investigation.json` |
| Split (registered before fitting) | `data/manifests/philippines_onset_split.json` |
| Feature schema | `vela/onset_features.py` (`onset_features_v1`) |
| Dataset + split assignment | `vela/onset_dataset.py` |
| Six-model comparison | `vela/onset_models.py` + `scripts/train_philippines_onset.py` |
| Holdout evaluation | `scripts/evaluate_philippines_onset.py` |
| Issued-forecast store | `data/observations/philippines_onset.sqlite` (write-once per cell×day) |
| Calendar / square API | `GET /api/onset/forecast?cell_id=…` |

**Target & issue time.** One forecast per 5 km land square, issued at **00:00 Asia/Manila**, valid for the following Philippine day. Live satellite heat may update after midnight; the issued onset forecast does not. Historical simulations must be labeled separately from forecasts actually issued by Vela.

**Input schemas (under `data/labels/philippines_onset/`)**

1. **Incidents** (`*incident*.csv|json`): `incident_id`, `onset_date_ph`, `latitude`, `longitude` (+ optional `province`, `wildfire_class`, `ongoing`, `date_precision`, `location_precision`, `source`). Accept only day-precision onset dates that resolve to one 5 km square. Reject report-only dates, ongoing fires, ambiguous locations, and non-wildfire classes (left unknown).
2. **Coverage** (`*coverage*.csv|json`): `coverage_date_ph`, `reporting_adequate`, plus `cell_id` or lat/lon. Adequate covered days without a start become negatives. Unmonitored / inadequate days stay unknown.

**Data audit (production labels today).** Import/audit counts are computed from files on disk (not hardcoded): usable unique wildfire starts **0**; square-days with credible reporting coverage **0**. BFP request **BFP-669031036800** (“Consolidated Forest Fire”, listed 2015–2024) could not be opened: eFOI portal returned **Temporary Maintenance (ADV-2026-10-01)** / Cloudflare block — attachment fields unverified. Davao DENR Region XI remains a **separate** acquisition lead. FIRMS heat is issue-time context only, never an onset label.

**States stay distinct.** `research_trained` → `holdout_evaluated` → `approved_for_serving`. Research training/selection does **not** publish a Live percentage. Synthetic fixtures used in tests are marked and never approve serving.

**Six classifiers.** Logistic regression, decision tree, random forest, Extra Trees, histogram gradient boosting, calibrated SVM, plus regional seasonal event-rate baseline. Preprocessing is fit on training folds only. Selection uses validation **Brier vs baseline** (not accuracy≈F1). Holdout is scored once afterward from actual held-out rows.

**Serving rules.** Square panel shows onset as **Not published** until serving is approved. Never fill gaps with 0%, FWI, or the harmonization model. Polygon summaries never average/max squares into a polygon-wide wildfire chance.

```bash
conda activate vela
python -m scripts.import_philippines_onset_labels
python -m scripts.audit_philippines_onset_labels
python -m scripts.train_philippines_onset
python -m scripts.evaluate_philippines_onset
python -m pytest tests/test_philippines_onset.py tests/test_philippines_onset_pipeline.py -q
```

**Plumbing proof.** `tests/test_philippines_onset_pipeline.py` builds a temporary synthetic incident+coverage pair and runs import → audit → train → evaluate through the normal commands. A known positive is counted once, a covered no-event day is negative, an unmonitored day stays absent/unknown, and the evaluator scores real holdout rows. Those artifacts stay isolated from production forecasts and accuracy claims.

**Next runnable step for real PH records.** Recover the BFP-669031036800 attachment when eFOI is back (or file DENR XI / LDRRMO microdata) under `data/labels/philippines_onset/`, then re-run import → audit → train → evaluate.

### Exact demo clicks

**Live draw-land (verified 14 November 2026 Asia/Manila)**

1. Fresh start → leave **Live** selected → do **not** pick a date or saved example.
2. **Draw area** a Maguindanao polygon around **6.85779°N, 124.05852°E** (e.g. 124.00–124.10°E, 6.82–6.90°N) → **Check my land**.
3. Browser request omits `date`; server uses `GET /api/live/today` → **2026-11-14**. UTC window queried: **2026-11-13** and **2026-11-14**.
4. Per-feed Live result for that polygon (zero readings is a successful query):

| Feed | Status | UTC window | Readings in polygon | Latest acquisition | Last successful check |
| --- | --- | --- | ---: | --- | --- |
| Aqua | `no_hotspots` | 2026-11-13 … 2026-11-14 | 0 | — | recorded |
| Suomi-NPP | `product_unavailable` | 2026-11-13 … 2026-11-14 | 0 | — | — |
| NOAA-20 | `no_hotspots` | 2026-11-13 … 2026-11-14 | 0 | — | recorded |
| NOAA-21 | `no_hotspots` | 2026-11-13 … 2026-11-14 | 0 | — | recorded |
| Terra (optional) | `no_hotspots` | 2026-11-13 … 2026-11-14 | 0 | — | recorded |

5. **Refresh now** re-queries FIRMS and writes a new `checked_at` into `philippines.sqlite` (national refresh wrote **65** rows on this pass). A repeat land check within the NRT **3 h** TTL reported `cached=true` for Aqua / NOAA-20 / NOAA-21 / Terra (Suomi-NPP stayed `product_unavailable`). Standard-processing cache entries do not expire.
6. Open **Philippines · 7 Nov 2026** (day becomes **2026-11-07**) → **Return to live** → day returns to **2026-11-14** and the next check-land again omits `date`.

Evidence: `data/metrics/mindanao_live_feed_probe.json`.

**Saved snapshot**

1. **Saved example** or **Philippines · 7 Nov 2026**.
2. **All Philippines → All Mindanao → All Philippines**: **47 → 12 → 47**. Masbate disappears and returns.
3. Nationwide saved readings: **43** on 7 Nov PH time, **4** on 8 Nov PH time.
4. Click Maguindanao cell `2393:174` → NOAA-21 · **12:33 PH** / 04:33 UTC.
5. In the square panel, open **Wildfire-onset forecast (next 24 hours)** → **Not published** (0 verified onset labels). Trace with `GET /api/onset/forecast?cell_id=2393:174&issue_date=2026-11-07` and `GET /api/onset/features?cell_id=2393:174&issue_date=2026-11-07`.
6. **Return to live** restores Philippine today without keeping the saved day as Live.

**History / calendar estimate**

1. With the Maguindanao polygon selected → **History** → year **2019** → week **2019-03-04/2019-03-10**.
2. Denominator diagnosis (`python -m scripts.diagnose_mindanao_denominator`): CMR catalog finds **66** granules (MYD14 12 · MYD03 24 · VNP14IMG 15 · VNP03IMG 15); **0** land-intersecting `paired_cells` rows; Aqua usable cell-days **0**; Suomi-NPP fallback inputs **0**; History contributions **unavailable**. First stage that drops to zero: **`2_land_intersecting_processed_rows`**.
3. Serving does **not** require jointly eligible Aqua–Suomi pairs for an operational estimate (`select_one`: Aqua alone → observed; eligible Suomi-NPP alone → calibrated fallback). Joint pairs are only for Agreement-with-Aqua.
4. Smallest viable archive download (not executed): **170 243 619 B** (~162.36 MB) for 2019-03-06 MYD14+MYD03+VNP14IMG+VNP03IMG. Blocked before ingest — no numerator/denominator/percentage to show on the calendar yet. See `data/metrics/mindanao_denominator_diagnosis.json`.

## Explore the Philippine Satellite Hotspot Map

[Open the Philippine hotspot map for 7 November 2026](data/public/philippines/2026-11-07.geojson)

Also available as: [Explore Philippine satellite detections — 7 November 2026](data/public/philippines/2026-11-07.geojson)

This is a verified **NASA FIRMS** snapshot for **7 November 2026 UTC**. Each GeoJSON point is one satellite heat detection. Multiple dots can come from the same event when more than one spacecraft (or pass) recorded heat nearby.

**Verified counts**

| Scope | Individual detections | By satellite |
| --- | ---: | --- |
| All Philippines | **47** | NOAA-20: 28 · NOAA-21: 17 · Terra: 2 |
| All Mindanao (same file, island-group filter) | **12** | NOAA-20: 5 · NOAA-21: 6 · Terra: 1 |

An earlier live Burn-activity screen (Terra unchecked) reported 45 detections and 39 grouped areas. Without Terra, this snapshot matches that **45** detection count; including Terra brings the Philippine total to **47**. Mindanao without Terra is **11** detections.

**How to open it in Vela (no FIRMS key)**

1. Start Vela and open **Burn activity**.
2. Under **Saved examples**, choose **Philippines · 7 Nov 2026**.
3. The map opens with **Show individual detections** enabled so the dots appear immediately. Toggle that checkbox off to return to the 5 km grouped view.
4. Use **All Philippines** / **All Mindanao** under the result lead to switch the same saved snapshot without a FIRMS key.
5. Click a dot to see satellite name, Philippine local date/time, and place name or coordinates in the vertical location panel. The sidebar stays navigation-only.

**Philippine-time split of the same 47 UTC readings**

| Philippine date | Readings |
| --- | ---: |
| 7 November 2026 | **43** |
| 8 November 2026 | **4** (late UTC passes after 16:00 UTC on the 7th) |

### Verified map clicks (browser)

Verified against the live app after restoring **All Philippines** / **All Mindanao** (static scripts under `app/static/js/`, Cache-Control: no-cache). On the saved **7 November 2026 UTC** snapshot:

| Step | Control | Individual detections | Areas | Camera extent (API bbox) | Masbate (Dalipe) |
| --- | --- | ---: | ---: | --- | --- |
| 1 | **All Philippines** | **47** | 41 | 114.10–126.80°E, 4.38–21.32°N | Present |
| 2 | **All Mindanao** | **12** | 11 | 117.97–126.74°E, 4.45–10.61°N | Absent |
| 3 | **All Philippines** | **47** | 41 | National extent restored | Returns |

Then click the Maguindanao del Norte heat marker:

| Field | Verified value |
| --- | --- |
| Cell | `2393:174` |
| Panel | “Heat detected once.” |
| Pass | **NOAA-21 · 12:33 PH time · 04:33 UTC · 1 reading** |

### Reproduce the map-to-estimate workflow

**1. Maguindanao del Norte marker (heat readings, no PH estimate)**

| Field | Value |
| --- | --- |
| Place | Maguindanao del Norte, Bangsamoro |
| Coordinates | 6.85779°N, 124.05852°E |
| Cell ID | `2393:174` |
| Source | `data/public/philippines/2026-11-07.geojson` (NASA FIRMS snapshot) |
| UTC acquisition | 7 November 2026 · 04:33 · NOAA-21 |
| Philippine time | 7 November 2026 · 12:33 |

Clicks:

1. **Burn activity** → **Philippines · 7 Nov 2026**
2. Optionally switch **All Philippines** ↔ **All Mindanao** (counts above)
3. Click the heat marker / square at Maguindanao del Norte (cell `2393:174`)
4. Open **History** (Monthly) for the same square/day

Expect: square panel lead “Heat detected once.”, NOAA-21 at 12:33 PH / 04:33 UTC, cell id shown, square scope labeled separately from the national boundary. History for 7 Nov shows **Satellite heat readings** / “Heat readings available · activity estimate not processed” — not “No stored observations.”

**Philippine validation gap (keep visible):** `paired_cells.parquet` has **0** Philippine rows; `/api/area-context` returns `calendar_status: not_processed` and region `not_in_training_sample`. No held-out Philippine harmonization error has been measured. Cached raw masks under `data/raw` are cerrado / California / Arnhem only — not this Mindanao cell.

**2. Date mismatch**

With the Maguindanao square open, change the panel date away from 7 Nov. Expect a notice naming both the marker date and the selected date, with **Use marker date** / **Query selected date**.

**3. Genuine numeric estimate (cached Zambia tune week — not Philippines)**

| Field | Value |
| --- | --- |
| Place | Zambia woodland |
| Cell ID | `523:-383` |
| Date | 2021-07-22 |
| Contributing platform | Suomi-NPP |
| Source | processed paired cells + frozen Suomi-NPP model |
| API | `GET /api/findings/zambia-fixture` |
| Model status | `estimated_suomi` |
| Estimate | ≈ **1.04%** (`model_probability` ≈ 0.01041) |
| Raw activity | `0` (zero fire pixels kept distinct from the probability) |

This **1.04%** is a **model estimate of Aqua-comparable activity for that square and day** (how likely Aqua would have been to detect heat there). It is **not** a Philippine result and **not** a wildfire probability. Or open the **Zambia woodland, 2021** saved example and inspect Research / weekly history for 19–25 July 2021 (~4.8% activity, 22 742 square-days, complete).

### Mindanao archive search (CMR / earthaccess)

Target: cell `2393:174` padded bbox `(123.95727, 6.78538, 124.10909, 6.92485)` — fire-mask + geolocation pairs for **Aqua MODIS** (`MYD14`/`MYD03`) and **Suomi-NPP VIIRS** (`VNP14IMG`/`VNP03IMG`).

**Exact reproducible queries** (NASA Earthdata CMR via `earthaccess.search_data`, netrc auth):

```python
bbox = (123.95727, 6.78538, 124.10909, 6.92485)
temporal = ("2026-11-02T00:00:00Z", "2026-11-08T23:59:59Z")
for short_name in ("MYD14", "MYD03", "VNP14IMG", "VNP03IMG"):
    earthaccess.search_data(short_name=short_name, bounding_box=bbox, temporal=temporal)
```

| Product | Live verify status | Count | Notes |
| --- | --- | ---: | --- |
| MYD14 | `ok_matches` (successful search) | 13 | Collection **061** archive + some LANCE |
| MYD03 | `ok_matches` | 24 | Geolocation present |
| VNP14IMG | `ok_matches` | 1 | Collection **002** · 2026-11-02 only |
| VNP03IMG | `ok_matches` | 1 | Paired with that VIIRS fire granule |

This is a **successful search with matches**, not a failed query. Same-day Aqua + Suomi-NPP fire/geo pairs for the week: **none** (`shared_utc_days: []`). Catalog footprint overlap alone cannot establish clear land. Records: `data/metrics/mindanao_cmr_2026-11-02_2026-11-08.json`, `mindanao_cmr_pair_plan.json`, `mindanao_cmr_live_verify.json`.

**A priori historical window** (order fixed before looking at fire outcomes): (1) FIRMS snapshot week → (2) first full week of March 2019 → (3) March 2020 fallback. March 2019 (`2019-03-04`–`2019-03-10`) has same-day Aqua+VIIRS catalog days. Smallest same-day candidate set (**2019-03-06**):

| File | Native id | Bytes |
| --- | --- | ---: |
| MYD14 | `MYD14.A2019065.0555.061.2020288164355` | 399 322 |
| MYD03 | `LAADS:4512480494` | 29 818 698 |
| VNP14IMG | `VNP14IMG.A2019065.0412.002.2024087125918` | 1 080 711 |
| VNP03IMG | `LAADS:6019938514` | 138 944 888 |
| **Total** | cache hits: **0** | **170 243 619 B (162.36 MB)** |

**No download executed** (`additional_bytes_needed` = 170 243 619). Without those local inputs the Mindanao activity estimate pipeline was **not** run. See `data/metrics/mindanao_2019-03_download_plan.json` and `mindanao_cmr_historical_windows.json`.

**Team feedback**

- Pull request / review link: https://github.com/jpwxts/VELA/pull/1

---

## What the map does

### Draw, search, check

1. Search a place (worldwide OpenStreetMap Nominatim) or **Draw my land**.
2. Choose a satellite observation date.
3. Tap **Check my land**.

FIRMS detections are clipped to your actual drawn boundary. Switching tabs preserves the polygon, zoom, selected square, date, satellite filters, and trends year.

For Philippine selections, place labels prefer **barangay → city/municipality → province**, and forecast dates use **Asia/Manila** time.

### Burn activity

Once land is selected, the pane leads with a compact summary: a map cutout of the boundary, the weekly burning-activity estimate for the observation date, and three-hour temperature and wind slots through today. Missing weekly history or weather is labeled unavailable rather than turned into a zero.

- Ember heat markers: **circle = 1 satellite**, **square = 2+ satellites**, with text labels in the legend.
- Click a square to see satellite names, local observation times (UTC also shown), and every original detection.
- Replay passes, compare “is this unusual here?”, and open a short weather teaser without losing the map.

### Weather outlook

Leads with **Why this day?** and up to seven forecast days.

For the selected day you see:

- Air temperature (°C)
- Relative humidity (%)
- Sustained wind and gusts (**km/h**)
- Wind direction in plain English (e.g. “from the northeast”)
- Forecast and recent rainfall (mm), with accumulation periods labeled
- Published **Fire Weather Index** when available, or **Fire-danger rating unavailable for this day**
- Source, valid date, and archive/update time when supplied

Point forecasts are labeled **Weather near the center of your selection.** Historical hotspot dates stay explicitly separate from current forecast dates.

**Fire danger sources**

| Source | How Vela uses it |
| --- | --- |
| [Open-Meteo](https://open-meteo.com/) | Live weather values |
| [GWIS / Copernicus ECMWF FWI](https://gwis.jrc.ec.europa.eu/) | Numeric fire-danger index at the forecast point |
| [ASMC Fire Weather Index map](https://asmc.asean.org/asmc-fire-fwi/) | Regional map reference for Southeast Asia / Philippines only — **never** inferred from image colors |

### History

The monthly calendar goes back to January 1990. Each day is labeled honestly:

- **Estimated burning activity** when coverage supports a complete or partial estimate
- **Satellite heat readings** when FIRMS/snapshot points exist but no estimate was processed
- **Not checked** for unqueried dates
- Gaps stay gaps — never inferred from an empty live FIRMS result

Replace the old “No stored observations” wording with the actual state (for example “Heat readings available · activity estimate not processed”).

The Weekly view retains the existing trends:

- Plain-language finding for the selected year (highest week, ties, or single available week).
- Compact calendar with readable ranges such as **19–25 July**.
- Complete vs partial vs unavailable weeks are visually distinct.
- Empty land/year states explain *why* (not processed, insufficient coverage, or failed request) and offer **View satellite readings** or **Choose an available year** when another year exists.

The weekly percentage estimates how often 5 km grid squares showed burning activity on days with usable estimates. It is **not** burned area and **not** a count of separate fires.

### Research

Three expandable questions a first-time visitor can follow:

1. **What did the satellite see?**
2. **How is fire danger calculated?**
3. **What would confirm a wildfire?**

Technical details (instruments, coverage rules, validation) sit under each answer. **Explore one grid square** walks through a real cell: what each satellite observed → what contributed → how it affects the weekly result.

---

## Honest limits

- Empty FIRMS results mean **no detections returned**, not a confirmed clear day. Coverage can still be unknown.
- Missing weather or FWI is labeled missing; a measured **0 mm** of rain is a quiet observation, not a gap.
- NOAA-20 and NOAA-21 raw heat stay on the map; harmonized estimates remain **calibration pending** until a measured transfer result exists.
- An unavailable satellite must not hide other satellites’ results. A weather failure must not erase heat markers.

Science rules for masks, pairing, coverage, and the model live in [`docs/METHOD.md`](docs/METHOD.md).

---

## Quick start

### 1. Environment

```bash
# Apple Silicon / conda-forge (example path used in development)
source "$HOME/miniforge3/etc/profile.d/conda.sh"
mamba env create -f environment.yml -p "$HOME/anaconda3/envs/vela"
conda activate "$HOME/anaconda3/envs/vela"

cp .env.example .env
python -m scripts.check_setup
```

Confirm the interpreter:

```bash
python -c "import sys; print(sys.executable)"
# should contain anaconda3/envs/vela
```

### 2. FIRMS map key (required for live map search)

**Every developer needs their own free key.** Searching the map calls NASA FIRMS live. The trained models and parquet tables on GitHub do **not** fill satellite detections for an arbitrary place/date. Without `FIRMS_MAP_KEY`, every satellite shows as unavailable / “Map key needed.”

1. Request a free key: [FIRMS map key](https://firms.modaps.eosdis.nasa.gov/api/map_key/)
2. `cp .env.example .env` and set `FIRMS_MAP_KEY=...` (no quotes)
3. Restart Vela after saving `.env`
4. Never commit `.env` or paste the key into chat

Until a key is set, use the **saved California** or **Zambia** examples to explore the UI. Weekly trends and Research still use the shared `data/processed` and `data/models` files from the repo.

### 3. Run the app

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 4. Optional: Earthdata (swath files & training)

```bash
earthaccess login
```

Needed only for granule download, smoke tests, and model-table builds—not for everyday FIRMS map checks.

---

## Try these flows in the UI

| Example | What to expect |
| --- | --- |
| **Competition example · California foothills** | Saved dated forecast + heat demo |
| **Saved weekly example · Zambia woodland · 2021** | One published week (~19–25 July) with estimates |
| Draw a plot in **Iloilo, Philippines** | Barangay/city/province place line, PH-time forecast dates, GWIS FWI when available, ASMC map link |
| Draw land with **no weekly history** | Clear empty state + path back to satellite readings |

---

## Project layout

```text
app/                 FastAPI server, FIRMS client, geocode, static UI
  static/            Single-page atlas: CesiumJS globe (globe.js) + rail and card (app.js)
vela/                Science & serving: grid, pairing, land check, preparedness, calendar
scripts/             Catalog, ingest, train, expansion, validation helpers
config/              Regions, settings, global plans
docs/                METHOD.md and validation notes
tests/               Pytest coverage for geocode, land check, preparedness, core rules
data/                Shared derived data + local raw granules (see below)
```

| Path | In GitHub? | Role |
| --- | --- | --- |
| `config/settings.json` | Yes | Grid, years, pair tolerance, smoke-test weeks |
| `config/regions.json` | Yes | Sample landscapes (Pantanal reserved) |
| `docs/METHOD.md` | Yes | Mask tables, 30-minute match, coverage rule, model splits |
| `data/catalog/` | Yes | Expansion / catalog summaries (`expansion_weeks.json`, …) |
| `data/manifests/` | Yes | Sample and expansion week manifests |
| `data/fixtures/` | Yes | UI fixtures and screenshots |
| `data/processed/` | Yes | Paired / excluded cell tables and pass shards |
| `data/models/` | Yes | Pilot / candidate models and selection JSON |
| `data/raw/` | **No** (~14 GB) | NASA HDF/NetCDF granules — fetch with Earthdata + scripts |

Raw granules are too large for GitHub. Clone the repo for tables and models; run `earthaccess login` and the ingest scripts if you need the original swaths.

---

## Data pipeline (optional)

```bash
python -m scripts.catalog_search          # search only; no download
python -m scripts.smoke_test              # one real pass after Earthdata login
python -m scripts.process_matched_passes  # process pairs already on disk
python -m scripts.make_manifest           # sample weeks (seed 42)
python -m scripts.build_table
python -m scripts.train_models            # safe before data exists; reports gaps
python -m scripts.ingest_expansion        # expansion batch → expansion_weeks.json
python -m pytest
```

**Model years:** train 2013–2020 · tune 2021–2022 · final test 2023–2024 (once). Pantanal is held out of development.

---

## Architecture (short)

```text
Browser (CesiumJS globe + land card)
        │
        ▼
FastAPI (app/main.py)
  /api/check-land      FIRMS (PH: overlapping UTC days) → polygon clip → hotspot areas + forecast
  /api/findings        Square/drawn-area passes, model estimate, weather
  /api/history/month   Estimates + FIRMS heat overlay for the calendar/chart
  /api/day-outlook     Open-Meteo → today’s temperature + wind slots
  /api/preparedness    Open-Meteo + GWIS FWI point forecast
  /api/calendar*       Weekly activity for the selected land
  /api/place           Nominatim reverse / search (cached)
  /api/trace           Example grid-square walkthrough
        │
        ▼
vela/  land_check · firms_day · findings · history · preparedness · hotspot_areas · serving
```

---

## Team & challenge

Built for **NASA Space Apps 2026** — category *Harmonization of MODIS and VIIRS*.

Repository: [github.com/jpwxts/VELA](https://github.com/jpwxts/VELA)

### Attribution

- NASA FIRMS active fire / hotspot detections  
- Aqua MODIS & Suomi-NPP / NOAA VIIRS fire masks  
- OpenStreetMap / Nominatim place data © OpenStreetMap contributors  
- Open-Meteo forecast API  
- Copernicus EMS GWIS ECMWF Fire Weather Index  
- ASMC / Malaysian Meteorological Department FDRS maps (regional reference)

---

## License & privacy

- Keep secrets in `.env` and Earthdata `.netrc` only.  
- `data/` large products and keys are gitignored.  
- Preparedness email briefs send only after review, and only if SMTP settings are configured.
