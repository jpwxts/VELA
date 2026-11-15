# Vela System Questions and Answers

## 1. What is Vela?

Vela is a map-first monitoring system that helps people examine satellite-detected heat and burning activity for land they search for or draw on an interactive globe. It combines observations, experimental estimates, weather context, and history while keeping their meanings separate.

## 2. What problem does Vela solve?

Satellite fire data is useful but often difficult for ordinary users to find, filter, and interpret for one specific property. Vela turns that technical data into a land-focused view so users can understand what satellites observed, what remains uncertain, and what may need closer attention.

## 3. Who can use the system?

Vela can support landowners, farmers, forest managers, researchers, local communities, and students who want to monitor a selected area. It is an awareness and research tool, not a replacement for emergency services, official fire reports, or field inspection.

## 4. How does a user check an area?

The user searches for a location or draws a boundary on the globe, selects the desired satellites and date, and asks Vela to check the land. The system then displays available heat detections, the selected land, relevant estimates, weather context, and historical records without requiring the user to work directly with raw satellite files.

## 5. What are Vela’s main features?

Vela includes an interactive 3D globe, place search, custom boundary drawing, satellite selection, hotspot markers, individual satellite readings, land cutouts, current weather, monthly history, charts, loading indicators, and probability shading where supported. The interface also works on desktop and mobile screens.

## 6. Why did we build Vela?

We built Vela to make Earth-observation data more understandable and useful at the scale people care about: their own land or community. The goal is to improve awareness while showing the limits of the data instead of hiding uncertainty behind a simple but potentially misleading warning.

## 7. What does a satellite hotspot mean?

A hotspot means that a satellite sensor recorded thermal activity that met the product’s detection rules at a particular place and time. It is evidence of detected heat, but it does not by itself prove the cause, exact burned area, fire severity, or danger to people.

## 8. Does a hotspot automatically mean there is a wildfire?

No. A hotspot may come from a vegetation fire, agricultural burning, industrial heat, or another thermal source, and the satellite pixel may cover a larger area than the actual heat source. Vela therefore describes hotspots as satellite-detected heat and does not automatically label every detection as a wildfire.

## 9. What does the displayed probability represent?

The probability represents the experimental chance that supported satellites will record at least one qualifying hotspot in a 5 km square during the next 24 hours. It is not the probability that a wildfire will start, spread, damage property, or endanger people.

## 10. Why should the system not turn weather or hotspot counts into a wildfire probability?

Fire weather, past hotspot counts, and current satellite observations describe different parts of the situation and are not interchangeable. Combining them without a separately trained and validated wildfire model would create a number that looks scientific but has no defensible meaning, so Vela keeps these answers separate.

## 11. Why can “no hotspots returned” be a logical error if shown as “no fire”?

A satellite search can return no detections because no qualifying heat was observed, but it can also be empty because of cloud, water, missing coverage, product delay, sensor limitations, or a failed request. Vela must only show a confident zero when usable coverage supports it; otherwise, the result remains unknown or unavailable.

## 12. How does Vela distinguish zero from missing data?

A zero means the system has sufficient usable observation evidence and found no qualifying heat for the relevant square and day. Missing data means that the system cannot make that statement because coverage, processing, or required inputs were incomplete, so missing values are kept as gaps rather than changed to zero.

## 13. Can two satellites detecting the same event cause double counting?

Yes, individual satellite readings can refer to the same heat event at slightly different positions or times. Vela keeps the original readings for transparency but groups nearby readings into common 5 km areas and identifies when more than one satellite contributed, reducing the risk of presenting duplicate observations as separate fires.

## 14. Why does Vela use 5 km grid squares?

The fixed grid gives observations and predictions a consistent spatial unit for comparing satellites, dates, and model outputs. A grid square is an analysis unit rather than a fire boundary, so users should not interpret the entire square as burned or assume the heat source fills it.

## 15. Why not average all square probabilities into one probability for the selected land?

Square predictions are related because nearby squares can share weather, observations, and fire conditions, so a simple average or combination can produce a misleading land-wide probability. Vela keeps probabilities attached to their squares and may summarize their range or expected count, but it does not claim a probability that any fire will occur across the whole polygon.

## 16. Could the continuous map gradient exaggerate differences between predictions?

Yes, a gradient can look informative even when backend probabilities are nearly identical, especially if colors are automatically stretched between the local minimum and maximum. Vela should use a fixed 0–100% scale, avoid per-selection rescaling, label the layer as experimental, and hide or explain surfaces that have too little variation to communicate a meaningful spatial difference.

## 17. Why might a very high probability still be unreliable?

A high score can result from a model receiving dates, locations, or input patterns that differ from its training data, and some model versions may be poorly calibrated. Vela preserves the original score for auditability but labels unsupported or out-of-distribution results as experimental and avoids presenting confidence that has not been demonstrated by independent evaluation.

## 18. How can two model versions produce very different answers for the same square?

Different model versions may use different training records, negative-label rules, features, calibration methods, or thresholds, so values such as 1% and 99% are not directly comparable unless their methods are the same. Vela should show the model version and issue time, preserve issued forecasts, and never silently replace an old forecast with a newly reconstructed one.

## 19. How does Vela prevent future information from leaking into a past prediction?

A valid forecast may only use information available before its stated issue time. Vela builds features using an issue-time cutoff, separates preserved issued forecasts from historical reconstructions, and must not use later detections or outcomes as if they had been known when the forecast was made.

## 20. Can a historical reconstruction be treated as a forecast that was actually issued?

No. A historical reconstruction applies the model to past data after the date has passed, while an issued forecast is a record preserved at the real decision time. Vela labels reconstructions clearly and keeps them separate so retrospective analysis does not create false evidence of past forecasting performance.

## 21. Does a calendar beginning in 1990 mean Vela has observations for every month since 1990?

No. The calendar allows users to choose dates from 1990 onward, but data availability depends on the satellite, product, archive, processing status, and selected location. Months without usable observations must remain unavailable rather than being shown as months with no burning activity.

## 22. Can current-day results change after the first check?

Yes. Satellite observations arrive at different times, near-real-time products can be revised, and a day may be incomplete while satellites are still passing over the area. Vela records observation and retrieval times, uses short-lived caches for recent data, and should not treat an incomplete current day as a final historical result.

## 23. What happens if an external service is slow or unavailable?

Vela uses bounded retries and graceful fallbacks so a temporary weather, place-search, map, or data-feed failure does not erase independent results that are already available. The interface shows loading and unavailable states, and major information such as satellite heat can load separately from slower weather or prediction requests.

## 24. How does Vela protect API credentials?

Credentials such as the NASA FIRMS map key and optional weather-service login stay on the server and are not sent to the browser or displayed in error messages. Public users receive only the processed response needed by the interface, while local environment files and personal credential files must remain outside version control.

## 25. Is Vela an official warning or emergency-response system?

No. Vela supports monitoring, education, and research, but it does not issue evacuation orders, confirm incidents on the ground, or replace government fire agencies and emergency hotlines. Users should verify urgent situations through official sources and local authorities.

## 26. What is Vela’s edge over existing hotspot maps?

Vela lets users work with their own boundary and brings detected heat, satellite provenance, weather, history, and experimental square-level estimates into one map-centered workflow. Its main advantage is not merely showing more data, but clearly separating observations from predictions, zero from missing data, and issued forecasts from later reconstructions.

## 27. What is the system’s most important design principle?

The most important principle is to avoid claiming more than the evidence supports. Every number should retain its source, time, spatial unit, and uncertainty so the interface remains useful without turning incomplete satellite data or experimental model output into false certainty.

## 28. How do we compute the model’s accuracy level?

Vela evaluates the predictor on labeled 5 km square-days whose satellite coverage is known, keeps training, validation, and test periods separate, chooses the decision threshold using validation data, and then reports performance on untouched test data. The main experimental HistGradientBoosting model currently has an audited validation F1 score of 0.606222 on 1,001 examples and a full-test F1 score of 0.589008 on 1,808 examples at a 0.1 threshold; these are audit results for the evaluated dataset, not a claim of 58.9% national wildfire accuracy.

## 29. Why does Vela report F1 instead of only ordinary accuracy?

Heat-positive square-days are less common than negative square-days, so a model could obtain a high ordinary accuracy simply by predicting “no detection” most of the time. F1 is more informative for this imbalance because it combines precision, which asks how many predicted positives were correct, and recall, which asks how many actual positives were found, using F1 = 2 × precision × recall ÷ (precision + recall).

## 30. What other measurements should accompany the F1 score?

Vela should also report the test-set size, classification threshold, confusion matrix, precision, recall, and probability-quality measures such as Brier score or calibration error. F1 measures the quality of yes-or-no decisions at one threshold, while calibration checks whether events shown near 20%, 50%, or 80% actually occur at roughly those rates, so neither measurement should be presented as a complete assessment by itself.

## 31. What counts as a correct positive or negative example?

A positive label means at least one qualifying MODIS or VIIRS satellite heat detection occurred inside a 5 km square during the target 24-hour window. A negative label is used only when the system has measured usable satellite coverage for that square and window but found no qualifying detection; a missing or failed observation is unknown and must not be treated as a negative.

## 32. How does Vela prevent information leakage during evaluation?

Every feature must be available at the forecast’s actual issue time, and later observations from the predicted window must never be used to construct that forecast. Time-separated training, validation, and test splits are kept fixed, the validation set is used for threshold or model selection, and the held-out test set is used only for final auditing so the score does not benefit from seeing the answers in advance.

## 33. What exactly does Vela’s predictive functionality estimate?

For each supported 5 km land square, the predictor estimates the chance of at least one qualifying MODIS or VIIRS satellite heat detection during the next 24 hours. It predicts a satellite-observable heat event, not wildfire ignition, fire size, damage, evacuation need, or the probability that any point in a large user-drawn polygon will burn.

## 34. Which inputs are used by the predictive model?

The frozen model uses heat detections from the previous 1, 3, and 7 days, neighboring heat from the previous 1 and 3 days, hours since the last detection, hours since the last usable satellite pass, the number of covered days and distinct satellites in the previous 7 days, whether heat persisted from yesterday, and seasonal month sine and cosine values. Fire-weather data is displayed as separate context and is not silently substituted for these satellite-history features.

## 35. How is the prediction produced from those inputs?

The backend builds the issue-time feature row for each square, verifies that the coverage, seasonal scope, and finite values satisfy the frozen model’s rules, and passes the ordered values to the HistGradientBoosting artifact to obtain a probability. The response retains the issue time, 24-hour target window, model name and hash, input provenance, limitations, and decision threshold so the browser can explain where the estimate came from.

## 36. What happens when the full predictive inputs are unavailable?

Vela does not invent missing detections, coverage, or weather; it uses the separately identified historical-rate fallback of 119 positive training square-days out of 589 eligible square-days, or 20.2037% displayed as 20.2%. This constant fallback does not distinguish one location from another and is not nationally calibrated, so it must be labeled as an experimental transferred base rate and must never inherit the stronger model’s F1 score.

## 37. Why does the fallback model have an F1 score of zero?

The fallback returns the same 20.2% probability for every eligible request, while its audited classification threshold is 50%, so it classifies every example as negative and finds none of the positive examples. Its validation and full-test F1 scores are therefore both 0, which does not mean the historical rate has no descriptive value; it means that this fallback is not a useful positive-event classifier at that threshold.

## 38. How is the probability shading drawn on the map?

The backend returns a probability for each evaluated 5 km square and the frontend converts those values into a continuous fixed color scale while clipping the surface to the evaluated land area. The scale should not be stretched separately for every selection because local rescaling can make small differences look dramatic, and a flat surface should be hidden or clearly identified rather than displayed as meaningful spatial variation.

## 39. How are results summarized for a user-drawn boundary?

Vela presents the range of individual square estimates and lets the user inspect each square’s percentage, issue time, observations, satellites, and method. The sum of the square probabilities, Σp, is only the expected number of heat-positive squares in the displayed set, not the probability of at least one fire, and large boundaries may use a spatial sample of at most 256 squares with the partial denominator stated explicitly.

## 40. What are the main components of the Vela system?

Vela consists of a map-based browser interface, a backend API, location and polygon-processing services, MODIS and VIIRS ingestion and harmonization, a persistent observation store, prediction feature and model services, weather retrieval, history and issued-forecast archives, caching and background refresh jobs, and verification tests. Each component has a distinct role so observed heat, predicted heat, weather danger, historical activity, and official reports are not merged into one misleading number.

## 41. What does the frontend component do?

The frontend displays the globe, location search, drawing tools, satellite selector, selected-land imagery, progress and loading states, hotspot layers, probability shading, weather outlook, and history calendar and chart. It requests independent data products from the backend, cancels or ignores outdated requests when the selection changes, and communicates whether each result is observed, predicted, unavailable, incomplete, or experimental.

## 42. What does the backend API do?

The backend validates dates and geometry, clips observations to the selected boundary, removes exact duplicates while preserving distinct satellite pixels or passes, groups readings into 5 km squares, builds model inputs, retrieves weather and history, and returns structured provenance and status information. It also keeps credentials on the server, limits expensive work, and allows heat, weather, prediction, and coverage requests to finish independently so one slow provider does not block the entire land check.

## 43. What do the ingestion, storage, and caching components do?

The ingestion pipeline retrieves supported FIRMS MODIS and VIIRS products, normalizes their fields and timestamps, distinguishes successful zero detections from failures, and writes usable observations to the persistent store. Caches reduce repeated provider calls, but recent incomplete days use short refreshable entries, failed results are not cached as successful data, and issued forecasts are keyed to observation and model versions so new evidence invalidates stale reuse without rewriting a genuinely issued historical estimate.

## 44. How do the history and weather components relate to the prediction?

History shows observed heat, genuinely issued next-24-hour estimates, and coverage-backed activity without creating forecasts retroactively, while weather reports separate dated fire-danger conditions. Both components add context, but neither changes a satellite-heat prediction after the fact, fills a missing satellite observation, or proves that a detected hotspot is a wildfire.

## 45. How do all components work together during a land check?

After the user searches for or draws land, the frontend sends its geometry to the API; the backend finds clipped satellite readings and covered squares, starts the forecast, weather, and history work independently, and returns each result with its own time, source, and state. The interface then renders actual observations and imagery, adds the experimental next-24-hour square estimates where supported, and keeps missing, loading, zero, failed, and completed states visibly different.

## 46. How should Vela validate a new region, season, or model update?

The team should first measure satellite coverage and label quality, define a time-based held-out test set, compare the proposed model with simple baselines, audit precision, recall, F1, calibration, geographic and seasonal performance, and failure cases, and record the exact dataset, code, model hash, and threshold. A new area or month should not be described as validated merely because the software can generate a number there; public promotion requires evidence that the model performs reliably in that scope.

## 47. What are the most important remaining limitations of the predictive system?

The current predictor is experimental, has limited evaluated seasons and geography, depends on satellite visibility and historical coverage, can miss short-lived or obscured heat, and may produce confident-looking values outside its learned distribution. Its existing full-test score is an audit of a fixed research split rather than national operational validation, so Vela must continue showing provenance, fallback status, uncertainty, and scope instead of presenting the output as an official warning.

## 48. How did we harmonize the satellite observations into one comparable dataset?

Vela does not simply combine every hotspot into one count: it first translates the Aqua MODIS and VIIRS fire-mask codes into the same categories—missing, water, cloud, clear land, unknown, and low-, nominal-, or high-confidence fire—then pairs each fire file with its matching geolocation file, matches Aqua and Suomi-NPP passes taken within 30 minutes, aligns them to the same local day, and places their pixel centers on the same equal-area 5 km grid. A square-day is usable only when both instruments observed at least half of its 25 km² land area as clear land or fire; cloud, water, sun glint, bow-tie deletion, unknown, and unprocessed pixels do not count, and missing coverage remains a gap rather than becoming zero. From matched square-days, the system learns how 14 Suomi-NPP VIIRS measurements—including fire-class counts, clear/cloud/water fractions, visible area, location, season, and local pass time—correspond to whether Aqua MODIS detected heat, with the selected frozen random-forest model converting eligible Suomi-NPP data into an Aqua-like activity probability. Each eligible square-day contributes only once, observed Aqua is preferred when available, calibrated Suomi-NPP is used when supported, and NOAA-20 and NOAA-21 remain visible as raw observations but are not called harmonized until separate transfer validation is completed; weekly and monthly activity then aggregate only these eligible contributions while preserving their platform, method, denominator, and missing-data status.

## 49. What does a red dot on the globe mean?

A red or ember-colored dot means that at least one selected satellite recorded a qualifying heat detection within that 5 km grid square on the chosen date; the marker is placed at the square’s center and is therefore not the exact location or boundary of a fire. A plain dot means the heat was reported by one satellite, while a dot with an outer red ring means two or more satellites reported heat in that square; clicking it shows the contributing satellites, reading count, times, and individual detections. It is evidence of satellite-observed thermal activity, not confirmation of a wildfire, its cause, size, severity, or the system’s predicted probability.
