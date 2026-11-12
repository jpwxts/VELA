# Harmonization rules

Vela compares Aqua MODIS and Suomi-NPP VIIRS on a fixed 5 km grid. The grid is the WGS 84 NSIDC EASE-Grid 2.0 projection (EPSG:6933) with 5 km cells, so each cell has an area of 25 km².

## Fire masks

Aqua MODIS `MYD14` Collection 6.1 uses Table 3 of the MODIS Collection 6/6.1 Active Fire Product User's Guide:

| Code | Meaning in Vela |
| --- | --- |
| 0, 1, 2 | Missing. Code 2 means not processed, not a clear pixel. |
| 3 | Water |
| 4 | Cloud |
| 5 | Clear land, no fire |
| 6 | Unknown |
| 7, 8, 9 | Fire at low, nominal, and high confidence |

Suomi-NPP `VNP14IMG` Collection 2 uses Table 1 of the Collection 2 VIIRS 375 m Active Fire User's Guide:

| Code | Meaning in Vela |
| --- | --- |
| 0, 1 | Missing. Code 1 is bow-tie deletion. |
| 2 | Unknown. This is sun glint, not MODIS code 2. |
| 3 | Water |
| 4 | Cloud |
| 5 | Clear land, no fire |
| 6 | Unknown |
| 7, 8, 9 | Fire at low, nominal, and high confidence |

A qualifying hotspot is any pixel in classes 7, 8, or 9. Low-confidence pixels stay in the fire class because that is how the official masks define them. Their counts are kept separate so a later rule can require nominal or high confidence.

## One cell-day

Fire and geolocation files are paired inside each platform when the acquisition time in the file name matches. Aqua and Suomi-NPP passes are paired when their start times differ by at most 30 minutes. That tolerance is `pair_tolerance_minutes` in `config/settings.json`.

Pixels outside the selected box are dropped. A box that crosses the international date line includes longitudes on both sides. Pixel centers fall into one 5 km cell. If several daytime pairs from the same VIIRS platform touch the same cell on the same local date, Vela keeps the pair that meets the coverage rule and has the most shared visible land. Ties prefer the pass closest to 13:30 local time. Suomi-NPP, NOAA-20, and NOAA-21 are not collapsed in that step.

The weekly calendar then gives each adequately observed cell-day exactly one contribution. A sensor can supply the cell only when its own visible land covers at least half of the 5 km cell. Aqua supplies the contribution when Aqua meets that test, including a clear zero. Otherwise one VIIRS platform is selected by visible-land coverage and then by closeness to 13:30 local time. Hotspot count is not used. The week reports how many cell-days have eligible coverage and how many of those have a valid activity estimate. Each selected cell-day is named as observed Aqua activity, raw VIIRS activity, a calibrated VIIRS estimate, or unavailable. Raw VIIRS activity stays visible and does not enter the activity-estimate total. If only some eligible cell-days have estimates, the activity total is partial and uses that smaller denominator. If none have estimates, the activity total is unavailable. Unknown coverage, including a FIRMS feed that returns zero records, is not a clear zero. NOAA-20 (`VJ114IMG` / `VJ103IMG`) and NOAA-21 (`VJ214IMG` / `VJ203IMG`) use the same VIIRS class table as Suomi-NPP. Their raw observations stay on the map, and their harmonized estimates stay calibration pending until a measured transfer result exists. Clicking the cell shows the platform that supplied it.

## Minimum shared coverage

A cell-day is usable only when land visible to both instruments covers at least half of the 25 km² cell. Visible land is clear land or a detected fire. Cloud, water, unknown, sun glint, bow-tie deletion, and unprocessed pixels do not count. Shared area is the smaller of the two visible-land areas. Nominal pixel areas are 1 km² for MODIS and 0.140625 km² for VIIRS (375 m × 375 m). Those are nadir areas; real pixels grow toward the edge of the scan.

If either sensor has no processed pixels, the cell-day is missing. Missing rows are stored with a reason and are not labeled “no fire.” The four labels used for a usable cell-day are:

- both detected
- VIIRS only
- MODIS only
- neither detected

The calendar metric is the share of usable cell-days with detected activity. It is not a count of individual wildfires and it is not the percentage of land burned.

## Model

Training rows are usable cell-days from 2013–2020 in the development landscapes. 2021–2022 are used only to choose a model. 2023–2024 are scored once, after that choice. The Pantanal window is reserved and is not used to fit or choose the model.

The target is whether Aqua MODIS detected at least one fire pixel. Inputs are VIIRS class counts, the visible-land area implied by those counts, cell latitude and longitude, the day of year, and the VIIRS local hour. MODIS measurements and the shared-coverage fields are not model inputs. The same feature function is used when only VIIRS is available. The frozen candidates were fit on Suomi-NPP only.

NOAA-21 FIRMS coverage starts in 2023. Those first two years are already the Suomi-NPP final test, so they are not reused for NOAA transfer. NOAA-20 matched evaluation is planned on 2021–2022. NOAA-21 matched evaluation is planned on 2025–2026. Neither plan downloads granules, refits the frozen candidates, or scores the final test. Until a measured transfer result exists, NOAA-20 and NOAA-21 harmonized estimates are labeled calibration pending.

The three estimates are raw VIIRS (any qualifying hotspot), logistic regression, and a random forest. Weekly activity is the average of the cell-day probabilities. Seasonal unusual-week thresholds are the 90th percentile of training-year weekly MODIS rates for a landscape and season, and only when at least four training weeks exist. A model is not selected when the training table does not have enough positives, years, regions, or tuning weeks. The map still runs.
