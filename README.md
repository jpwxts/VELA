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
