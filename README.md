# Vela — Check my land

**Vela** is a map-first web app for the [NASA Space Apps](https://www.spaceappschallenge.org/) challenge *Harmonization of MODIS and VIIRS Hot Spots*.

You draw or search for a plot of land, pick a date, and explore four questions in one panel—without leaving the map:

| Tab | Question it answers |
| --- | --- |
| **Where is this?** | What heat did the satellites see on this land, grouped in 5 km squares? |
| **Weather outlook** | Which day has the highest fire danger near this land, and why? |
| **Weekly trends** | When was burning activity highest on this land? |
| **Research** | How did Vela reach this result? |

Vela keeps **satellite heat**, **fire-danger weather**, **weekly activity estimates**, and **official wildfire reports** as separate answers. It never turns FWI, hotspot counts, MODIS confidence, or the harmonization model into a wildfire probability.

---

## What the map does

### Draw, search, check

1. Search a place (worldwide OpenStreetMap Nominatim) or **Draw my land**.
2. Choose a satellite observation date.
3. Tap **Check my land**.

FIRMS detections are clipped to your actual drawn boundary. Switching tabs preserves the polygon, zoom, selected square, date, satellite filters, and trends year.

For Philippine selections, place labels prefer **barangay → city/municipality → province**, and forecast dates use **Asia/Manila** time.

### Where is this?

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

### Weekly trends

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
  static/            Single-page map (Leaflet) + panel tabs
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
Browser (Leaflet map + land panel)
        │
        ▼
FastAPI (app/main.py)
  /api/check-land      FIRMS → polygon clip → hotspot areas + forecast
  /api/preparedness    Open-Meteo + GWIS FWI point forecast
  /api/calendar*       Weekly activity for the selected land
  /api/place           Nominatim reverse / search (cached)
  /api/trace           Example grid-square walkthrough
        │
        ▼
vela/  land_check · preparedness · calendar_metrics · hotspot_areas · serving
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
