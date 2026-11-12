# Vela — The Fire Time Machine

Vela is a local map for the NASA Space Apps challenge “Harmonization of MODIS and VIIRS Hot Spots.” You pick any area and a date. The app asks NASA FIRMS for hotspot detections and, once real swaths have been processed, compares Suomi-NPP VIIRS with what Aqua MODIS saw.

This copy was set up on an Apple M1 Mac, macOS 15.7.4, with 8 GB of memory. About 44 GB was free after installation. Anaconda 23.9 was already installed, but its solver did not finish the scientific packages. Miniforge for Apple Silicon was installed at `~/miniforge3` and used to create the `vela` environment inside Anaconda, at `~/anaconda3/envs/vela` (about 1 GB). The Python 3.14 app that came with the Mac is not used. Do not download every year in the sample manifest onto this Mac.

## 1. Create the environment

The environment is already created on this Mac. In a new terminal, activate it:

```bash
source "$HOME/anaconda3/etc/profile.d/conda.sh"
cd ~/Desktop/MODISVIIRS
conda activate vela
python -c "import sys; print(sys.executable)"
```

The printed path must contain `anaconda3/envs/vela`. If `conda activate vela` says the environment does not exist, use Miniforge’s conda instead:

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda activate /Users/florlyn/anaconda3/envs/vela
```

To recreate the environment on another day:

```bash
source "$HOME/miniforge3/etc/profile.d/conda.sh"
mamba env create -f environment.yml -p "$HOME/anaconda3/envs/vela"
```

```bash
cp .env.example .env
python -m scripts.check_setup
```

## 2. Start the map

Leave the environment active and run:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Search for a place or draw a rectangle, choose a date, then press **Use this area and date**. Moving the map does not call NASA. FIRMS returns detections only, so an empty result is labeled “No hotspots returned” and “Coverage unknown.” It is not a confirmed clear day. Standard-processing products are used for historical dates. A near-real-time product is used only when the date is outside the standard range and inside the near-real-time range. One request covers one day because the FIRMS area API allows a window of 1 to 5 days.

The map key is read from `.env` on your Mac. It is not put in the page, in Git, or in the app log.

### Map key

1. Open [the FIRMS map-key page](https://firms.modaps.eosdis.nasa.gov/api/map_key/) and request a free key.
2. When the email arrives, open `.env` in this folder.
3. Put the key after `FIRMS_MAP_KEY=` with no quotes.
4. Save. In the terminal where Vela is running, press Control-C, then start the app again with the command above.

Do not paste the key into chat.

## 3. Earthdata login

Swath files need a free [Earthdata Login](https://urs.earthdata.nasa.gov/users/new). In a terminal where `vela` is active, run:

```bash
earthaccess login
```

Type the username and password in that terminal. If a browser asks you to authorize access, choose Authorize. Do not paste the password into chat.

## 4. Search the catalog

This does not download files. It prints unique files, candidate daytime passes, estimated transfer size, and how many files have an unknown size. If the first configured week has no pair, it tries the next week in `config/settings.json`.

```bash
python -m scripts.catalog_search
```

## 5. Read one real pass

After Earthdata login:

```bash
python -m scripts.smoke_test
python -m scripts.verify_readers --modis data/raw/<region>/<date>/MYD14....hdf --viirs data/raw/<region>/<date>/VNP14IMG....nc
```

Use the two fire-mask paths printed by the smoke test. The check has to read the mask arrays. Importing the libraries is not enough. In the app, **Show traced cell** lists one VIIRS-only cell and one MODIS-only cell from that pass.

To add the other daytime pairs from the saved catalog, without downloading files already on disk:

```bash
python -m scripts.process_matched_passes
```

## 6. Sample, then a bounded training run

The manifest is written before any download. It uses random seed 42, whole weeks from 2013 through 2024, several landscapes, quiet-season weeks, and keeps the Pantanal window out of model development.

```bash
python -m scripts.make_manifest
python -m scripts.train_models
```

`train_models` is safe to run before data exists. It prints the positives, years, and regions that are still missing, and it does not invent a score. After a real `paired_cells.parquet` exists:

```bash
python -m scripts.build_table
python -m scripts.train_models
```

To search, optionally download one pass, and then train:

```bash
python -m scripts.run_bounded
python -m scripts.run_bounded --download
```

Bulk retrieval is a separate command. It prints the estimate and downloads only when you add `--download`:

```bash
python -m scripts.bulk_acquire --limit-weeks 1 --region cerrado
python -m scripts.bulk_acquire --limit-weeks 1 --region cerrado --download
```

## 7. Held-out demo

Training years are 2013–2020. Tuning years are 2021–2022. The final test years are 2023–2024 and are scored once, after the model is chosen. The Pantanal sample window is reserved.

When a trained model and usable held-out observations both exist, open a 2023 or 2024 week and press **Reveal MODIS**. Before that, the panel shows the VIIRS activity and the MODIS-equivalent estimate. Reveal adds the Aqua MODIS rate, the difference in percentage points, and the shared coverage. The frozen harmonized candidates use Suomi-NPP. NOAA-20 and NOAA-21 stay labeled on the map. Their harmonized estimates say calibration pending until a measured transfer result exists. The combined-observations summary sits above the satellite cards and keeps an all-empty query at 0 returned records while coverage is unknown.

The weekly number is the share of usable cell-days with detected activity. It is not a count of wildfires and it is not the percentage of land burned. Weeks without enough shared clear land use a hatched pattern. A hatched week is not a zero.

**Download CSV** saves the selected year. Held-out Aqua MODIS values stay out of that file unless the address includes `include_observed=true`.

## Tests

```bash
python -m pytest
```

The synthetic HDF4 and NetCDF files created by the tests are software fixtures. They are not NASA observations and they are not model scores.

## Where the science rules live

`docs/METHOD.md` records the mask tables, the 30-minute match, the 5 km grid, and the minimum shared-coverage rule.

## Useful paths

| Path | What it is |
| --- | --- |
| `config/settings.json` | Grid, years, tolerance, and the two smoke-test weeks |
| `config/regions.json` | Sample landscapes, including the reserved Pantanal window |
| `data/manifests/sample_manifest.csv` | Week sample, written before download |
| `data/processed/paired_cells.parquet` | Usable cell-days |
| `data/processed/excluded_cells.parquet` | Rows left out, with reasons |
| `data/models/report.json` | Gaps, or the single test result |
