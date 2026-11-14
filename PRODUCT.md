# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

People who want to know what satellites saw over a piece of land: someone with a farm, plot, forest or park to watch, and NASA Space Apps readers judging the project. They arrive with one place in mind and the question "what should I watch on my land?" (Inferred from the README and the app's own copy; not yet confirmed by the team.)

## Product Purpose

Vela is a map-first web app for the NASA Space Apps challenge *Harmonization of MODIS and VIIRS Hot Spots*. A visitor finds or draws land, picks an observation date, and reads four separate answers without leaving the map: satellite heat seen on the land, the fire-weather outlook, weekly burning-activity history, and how Vela reached the result.

## Positioning

Vela keeps satellite heat, fire-danger weather, weekly activity estimates and official wildfire reports as separate answers. It never turns FWI, hotspot counts, MODIS confidence or the harmonization model into a wildfire probability.

## Operating Context

- FastAPI backend in `app/`, static frontend in `app/static/` (plain HTML, CSS and JavaScript, no build step).
- Live satellite search needs each developer's own free NASA FIRMS key in `.env`; saved examples (California foothills, Zambia woodland 2021) work without one.
- Weather comes from Open-Meteo and the Copernicus GWIS Fire Weather Index; place names from OpenStreetMap Nominatim.
- Philippine selections prefer barangay, city or municipality, province labels and Asia/Manila time.

## Capabilities and Constraints

- Confirmed by the user (2026-11-14): the map is an interactive CesiumJS globe. The app opens on the whole globe with the land widget hidden. Selecting a place or finishing a drawn boundary opens the widget; clearing the selection hides it again.
- Confirmed by the user (2026-11-14): every existing feature stays, rehomed into the new layout: place search, the two saved examples, satellite selection, replay of satellite passes, weekly trends with CSV download, the grid-square trace, weather outlook and research notes.
- Heat is grouped into 5 km observation squares; a square seen by two or more satellites is marked differently from one seen by a single satellite.
- A missing detection is never presented as "no heat".
- No Cesium ion token is used: basemap and terrain come from keyless public services.
- Confirmed by the user (2026-11-14): once land is selected, the Burn activity pane leads with a summary: a cutout of the drawn land, the weekly burning-activity percentage, and temperature and wind through today. The user chose the existing weekly burning-activity estimate for the big figure over a "chance of a wildfire"; where no weekly estimate exists the summary says so.
- History opens on a monthly burning-activity calendar with month/year selection back to January 1990, daily details, and a bar chart that switches between the selected month and year. Values come from stored cell-day observations within the drawn boundary. Unavailable periods stay missing; the date range does not imply observations exist for every year.

## Brand Commitments

- Name: Vela. Wordmark in lowercase with a flame mark.
- The user pinned a visual reference on 2026-11-14 (four "Vela · Fire atlas" screenshots): a left rail with four destinations (Burn activity map, History, Weather outlook, Research), flat water, land drawn with contour lines, ember-red heat dots, a teal active state, serif display headings and small monospace labels on a floating detail card. The old interface is not a reference.
- Later the same day the user revised that reference, and these revisions win over the screenshots: the whole interface is dark; the rail shows icons only, with names in tooltips; the header carries only the wordmark; the globe has no reset, zoom or compass controls; Draw area is a pencil icon; standing hint text and the footer source line are removed; the legend opens from a button at the foot of the rail; search uses a magnifier icon; a subtle star field sits behind the globe; the bottom-right credit texts are removed and the map data credit lives inside the legend panel.

## Evidence on Hand

- Saved fixtures in `data/fixtures/` (land check demo, hotspot click regressions, weather outlooks).
- Method and validation notes in `docs/`.
- No testimonials, customers or benchmarks exist; none may be invented.

## Product Principles

1. Four questions, four separate answers. Never blend them into one risk score.
2. Say what was measured and what was not. Missing data is named as missing.
3. The map is the workspace; detail opens beside it, never instead of it.
4. Every number shown is real or clearly labelled as a saved example.
