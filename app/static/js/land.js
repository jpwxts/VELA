// Choosing land (search, drawing, saved box) and checking it for heat.

function updateDayWords() {
  const node = document.querySelector("#day-words");
  const value = dayInput.value;
  if (!value) {
    node.textContent = "Choose a date.";
    return;
  }
  node.textContent = formatObservationDay(value);
  const previousMonth = state.calendarMonth;
  state.calendarMonth = value.slice(0, 7);
  state.historyDay = value;
  renderObservationCalendar();
  renderDaySummary();
  updateSelectionBanner();
  if (state.polygon && state.polygon.length >= 4) loadWeeklyActivity();
  if (previousMonth !== state.calendarMonth && state.panelTab === "weekly" && state.historyView === "present") loadMonthlyHistory();
}

async function loadStatus() {
  const response = await fetch("/api/status");
  if (!response.ok) return;
  const payload = await response.json();
  const metric = document.querySelector("#metric");
  if (metric) metric.textContent = payload.metric;
  const note = document.querySelector("#metric-note");
  if (note) {
    note.textContent =
      "A square observed on Monday and Tuesday counts twice, once for each day. The value measures activity frequency; it is not the percentage of land burned or a count of separate fires.";
  }
  const researchMetric = document.querySelector("#metric-research");
  if (researchMetric) researchMetric.textContent = payload.metric;
  const keyBanner = document.querySelector("#firms-key-banner");
  if (keyBanner) {
    if (payload.firms_configured) {
      keyBanner.hidden = true;
      keyBanner.textContent = "";
    } else {
      keyBanner.hidden = false;
      keyBanner.innerHTML =
        "Live satellite search needs a free NASA FIRMS map key. Copy <code>.env.example</code> to <code>.env</code>, add <code>FIRMS_MAP_KEY</code>, restart Vela. "
        + "Trained tables on GitHub do not replace FIRMS. Until then, use the saved California or Zambia examples.";
    }
  }
}

async function searchPlace() {
  const query = document.querySelector("#search").value.trim();
  const list = document.querySelector("#places");
  list.innerHTML = "";
  if (query.length < 2) return;
  const response = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`);
  if (!response.ok) {
    list.innerHTML = "<li>Place search failed. Check your connection, or draw the boundary instead.</li>";
    return;
  }
  const payload = await response.json();
  payload.places.forEach((place) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = place.name;
    button.addEventListener("click", () => {
      list.innerHTML = "";
      state.placeName = place.name;
      setBox([place.west, place.south, place.east, place.north], place.name);
      // Place search starts from a rectangle visitors can edit into a tighter plot.
      setPolygonFromBox(state.box, place.name);
      openLandPanel({ tab: "where", focus: false });
      checkLand();
    });
    item.append(button);
    list.append(item);
  });
  if (!payload.places.length) list.innerHTML = "<li>No place matches that name. Try a nearby town or province.</li>";
}

function setBox(box, label) {
  state.box = box.map((value) => Number(Number(value).toFixed(4)));
  const [west, south, east, north] = state.box;
  clearRectangle();
  const parts = west <= east ? [[west, east]] : [[west, 180], [-180, east]];
  // Light dashed search/land boundary, distinct from the teal cell selection.
  state.rectangle = parts.map(([left, right]) => globe.addArea(
    [[left, south], [right, south], [right, north], [left, north]],
    { stroke: LAND_STROKE, weight: 2, dashed: true, fill: LAND_STROKE, fillOpacity: 0.03 }
  ));
  state.landBoundaryLabel = globe.addOverlay(
    north,
    (west + east) / 2,
    mapBadge("Search boundary", "land-boundary-label"),
    "above"
  );
  flyToBounds({ west, south, east, north }, { minSpan: 0.3 });
  if (label) {
    document.querySelector("#area-label").textContent =
      `${label}. West ${west}, south ${south}, east ${east}, north ${north}.`;
  }
}

function setPolygonFromBox(box, label) {
  const [west, south, east, north] = box;
  setPolygon(
    [
      [west, south],
      [east, south],
      [east, north],
      [west, north],
      [west, south],
    ],
    label || "Selected place boundary"
  );
}

function setPolygon(coordinates, label) {
  const ring = coordinates.map(([lon, lat]) => [Number(lon), Number(lat)]);
  if (ring.length && (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1])) {
    ring.push([...ring[0]]);
  }
  state.polygon = ring;
  state.historyRequestId += 1;
  state.monthHistory = null;
  state.historyKey = null;
  state.historyLoading = false;
  state.historyError = false;
  const lons = ring.map((point) => point[0]);
  const lats = ring.map((point) => point[1]);
  state.box = [
    Math.min(...lons),
    Math.min(...lats),
    Math.max(...lons),
    Math.max(...lats),
  ].map((value) => Number(value.toFixed(4)));
  // Invalidate any in-flight outlook for the previous plot.
  state.weatherRequestId += 1;
  state.selectedForecastDay = null;
  clearPolygonLayers();
  clearRectangle();
  state.polygonLayer = globe.addArea(ring, {
    stroke: LAND_STROKE,
    weight: 2.5,
    dashed: true,
    fill: LAND_STROKE,
    fillOpacity: 0.05,
  });
  state.savedExample = false;
  const [west, south, east, north] = state.box;
  openLandPanel({ tab: "where", focus: false });
  flyToBounds({ west, south, east, north }, { minSpan: 0.12 });
  // A new boundary starts a new record: earlier checks and place names belonged to other land.
  state.checkedDays.clear();
  state.lastPlace = null;
  state.placeRequestId += 1;
  state.landLabel = label || "Your land";
  document.querySelector("#area-label").textContent =
    `${label || "Your land"}. ${ring.length - 1} corners. You can redraw after checking.`;
  document.querySelector("#map-hint").textContent = "Boundary selected. Choose Check my land.";
  clearWeatherOutlook();
  updateSelectionBanner();
  renderObservationCalendar();
  renderDaySummary();
  refreshLandSummary();
}

function clearRectangle() {
  if (state.rectangle) {
    const layers = Array.isArray(state.rectangle) ? state.rectangle : [state.rectangle];
    layers.forEach((layer) => layer.remove());
    state.rectangle = null;
  }
  if (state.landBoundaryLabel) {
    state.landBoundaryLabel.remove();
    state.landBoundaryLabel = null;
  }
}

function clearPolygonLayers() {
  if (state.polygonLayer) {
    state.polygonLayer.remove();
    state.polygonLayer = null;
  }
  if (state.draftLayer) {
    state.draftLayer.remove();
    state.draftLayer = null;
  }
}

function clearForecastMarker() {
  if (state.forecastMarker) {
    state.forecastMarker.remove();
    state.forecastMarker = null;
  }
}

function clearLand() {
  state.historyRequestId += 1;
  state.monthHistory = null;
  state.historyKey = null;
  state.historyLoading = false;
  state.historyError = false;
  state.box = null;
  state.polygon = null;
  state.polygonDraft = [];
  state.drawing = false;
  state.anchor = null;
  state.lastLandCheck = null;
  state.forecast = null;
  state.selectedForecastDay = null;
  state.weatherRequestId += 1;
  clearRectangle();
  clearPolygonLayers();
  clearForecastMarker();
  clearMapLayers();
  state.lastPayload = null;
  state.selectedArea = null;
  state.lastPlace = null;
  state.placeName = null;
  state.landLabel = null;
  state.placeRequestId += 1;
  state.checkedDays.clear();
  state.checkingDay = null;
  // Any land check still in flight belongs to the land that was just cleared.
  state.landRequestId += 1;
  setChecking(false);
  setDrawing(false);
  document.querySelector("#cell-detail").hidden = true;
  document.querySelector("#public-result").hidden = true;
  document.querySelector("#land-summary").hidden = true;
  document.querySelector("#land-secondary-content").hidden = false;
  state.cutoutToken += 1;
  state.activityRequestId += 1;
  state.outlookRequestId += 1;
  state.summarySquare = null;
  syncLandPicture();
  document.querySelector("#area-label").textContent =
    "Search for a place or draw a boundary on the globe, then check it for satellite heat.";
  document.querySelector("#map-hint").textContent = "Turn the globe to your land, then search or draw its boundary.";
  resetLandResult();
  clearWeatherOutlook();
  updateSelectionBanner();
  renderObservationCalendar();
  renderDaySummary();
  closeAreaPanel();
}

function setDrawing(on) {
  state.drawing = Boolean(on);
  document.querySelector("#finish-draw").hidden = !on;
  document.querySelector("#draw").setAttribute("aria-pressed", on ? "true" : "false");
  // The on-globe hint appears only while drawing, where it counts the corners placed.
  document.querySelector("#map-hint").hidden = !on;
}

// The Check button shows its own progress, since results land in the same pane.
function setChecking(on) {
  const button = document.querySelector("#confirm");
  button.disabled = Boolean(on);
  button.textContent = on ? "Checking…" : "Check my land";
}

function startPolygonDraw() {
  // Pressing Draw area again while drawing cancels the unfinished boundary.
  if (state.drawing) {
    setDrawing(false);
    state.polygonDraft = [];
    if (state.draftLayer) {
      state.draftLayer.remove();
      state.draftLayer = null;
    }
    document.querySelector("#map-hint").textContent = "Drawing cancelled.";
    return;
  }
  setDrawing(true);
  state.polygonDraft = [];
  clearPolygonLayers();
  document.querySelector("#area-label").textContent =
    "Click the corners of your plot on the globe. Choose Finish boundary once you have at least three.";
  document.querySelector("#map-hint").textContent =
    "Drawing: click each corner of your land, then choose Finish boundary.";
}

function addPolygonVertex(spot) {
  state.polygonDraft.push([spot.lon, spot.lat]);
  if (state.draftLayer) state.draftLayer.remove();
  state.draftLayer = globe.addPath(state.polygonDraft, { stroke: LAND_STROKE, weight: 2, dashed: true });
  const placed = state.polygonDraft.length;
  const words = `${placed} corner${placed === 1 ? "" : "s"} placed.`;
  document.querySelector("#area-label").textContent = `${words} Finish when ready.`;
  document.querySelector("#map-hint").textContent =
    placed < 3 ? `${words} Add at least three.` : `${words} Choose Finish boundary when the shape is right.`;
}

function finishPolygonDraw() {
  if (state.polygonDraft.length < 3) {
    document.querySelector("#area-label").textContent = "Add at least three corners before finishing.";
    document.querySelector("#map-hint").textContent = "Add at least three corners before finishing.";
    return;
  }
  setDrawing(false);
  state.placeName = null;
  const draft = state.polygonDraft;
  state.polygonDraft = [];
  if (state.draftLayer) {
    state.draftLayer.remove();
    state.draftLayer = null;
  }
  setPolygon(draft, "Drawn land");
  openLandPanel({ tab: "where", focus: false });
  // There is no Check button beside the summary: selecting land checks it.
  checkLand();
}

function selectedPlatforms() {
  return [...document.querySelectorAll(".satellite-details fieldset input:checked")].map((node) => node.value);
}

function setDefaultPlatforms() {
  document.querySelectorAll(".satellite-details fieldset input").forEach((node) => {
    node.checked = DEFAULT_PLATFORMS.includes(node.value);
  });
}

function resetLandResult() {
  document.querySelector("#fixture-banner").hidden = true;
  document.querySelector("#separation-note").hidden = true;
  document.querySelector("#heat-block").hidden = true;
  document.querySelector("#heat-inside").innerHTML = "";
  document.querySelector("#heat-nearby").innerHTML = "";
  document.querySelector("#heat-feeds").innerHTML = "";
  document.querySelector("#weather-headline").textContent = "Checking your land…";
  document.querySelector("#weather-explanation").textContent =
    "Loading the fire-danger outlook and recent satellite heat.";
  document.querySelector("#weather-status").textContent = "Loading…";
}

async function checkLand(options = {}) {
  if (!state.polygon || state.polygon.length < 4) {
    document.querySelector("#area-label").textContent = "Draw or select your land first.";
    return;
  }
  let platforms = selectedPlatforms();
  if (!platforms.length) {
    setDefaultPlatforms();
    platforms = [...DEFAULT_PLATFORMS];
  }
  const date = dayInput.value;
  document.querySelector("#year").value = date.slice(0, 4);
  const requestId = ++state.landRequestId;
  ++state.requestId;
  resetLandResult();
  state.landLabel = options.label || state.landLabel || "Your land";
  state.checkingDay = date;
  setChecking(true);
  document.querySelector("#area-label").textContent =
    `Checking satellite heat for ${formatObservationDay(date)}…`;
  renderDaySummary();
  openLandPanel({ tab: state.panelTab || "where", focus: false });
  try {
    const response = await fetch("/api/check-land", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        coordinates: state.polygon,
        date,
        platforms,
        label: options.label || "Your land",
      }),
    });
    const payload = await response.json();
    if (requestId !== state.landRequestId) return;
    renderLandCheck(payload);
  } catch (error) {
    if (requestId !== state.landRequestId) return;
    state.checkingDay = null;
    setChecking(false);
    document.querySelector("#area-label").textContent =
      "The land check failed. Check your connection, then choose Check my land again.";
    document.querySelector("#weather-headline").textContent = "The land check failed.";
    document.querySelector("#weather-explanation").textContent = "Check your connection and try again.";
    document.querySelector("#weather-status").textContent = "Retry with Check my land.";
    renderDaySummary();
  }
}

function setResultLead(text) {
  const node = document.querySelector("#result-lead");
  if (node) node.textContent = text;
}

function renderLandCheck(payload) {
  state.lastLandCheck = payload;
  state.forecast = payload.forecast || null;
  state.checkingDay = null;
  state.savedExample = Boolean(payload.fixture || payload.saved);
  setChecking(false);
  document.querySelector("#area-label").textContent =
    `Checked for ${formatObservationDay(payload.observation_date || dayInput.value)}. Change the date or redraw to check again.`;
  document.querySelector("#map-hint").textContent = "Click a heat dot, or any spot inside your boundary, for details.";
  const fixture = payload.fixture;
  const banner = document.querySelector("#fixture-banner");
  if (fixture?.label || payload.saved) {
    banner.hidden = false;
    banner.textContent = fixture?.label || "Saved competition demo · labeled archive, not a live network pull";
  } else {
    banner.hidden = true;
  }

  const separation = document.querySelector("#separation-note");
  separation.hidden = false;
  separation.textContent = payload.separation_note || "";

  const forecast = payload.forecast || {};
  state.landLabel = payload.label || state.landLabel || "Your land";
  // Weather tab reuses the same outlook renderer; keep the map-centered marker.
  renderOutlook(forecast, weatherSelectors());
  clearForecastMarker();
  const point = forecast.point || {};
  if (point.latitude != null && point.longitude != null) {
    state.forecastMarker = globe.addPoint(point.latitude, point.longitude, {
      radius: 5,
      fill: "#fffdf8",
      stroke: CELL_STROKE,
      weight: 2.5,
      tooltip: point.label || "Weather near the center of your selection.",
    });
    syncForecastMarkerVisibility();
  }
  const researchPerf = document.querySelector("#research-performance");
  if (researchPerf) {
    researchPerf.textContent = `Harmonization validation: ${(forecast.performance || payload.forecast?.performance || {}).text || "Pending verification."}`;
  }

  const heat = payload.heat || {};
  document.querySelector("#heat-block").hidden = false;
  document.querySelector("#heat-lead").textContent = heat.lead || "";
  document.querySelector("#heat-feeds").innerHTML = renderFeedBreakdown(heat.feeds || []);
  document.querySelector("#heat-inside").innerHTML = renderHeatGroup(
    "Inside your boundary",
    heat.inside || []
  );
  document.querySelector("#heat-nearby").innerHTML = renderHeatGroup(
    "Nearby (outside the boundary)",
    heat.nearby || [],
    true
  );
  document.querySelector("#incident-line").textContent = payload.incident?.line || "";

  // Same map rendering path as saved-place / Show hotspots: polygon-filtered areas + individuals.
  state.multiOnly = false;
  clearMapLayers();
  const synthetic = {
    date: payload.observation_date,
    results: [],
    hotspot_areas: heat.hotspot_areas || { areas: [], area_count: 0, detection_count: 0, multiple_satellite_area_count: 0 },
    public_result: heat.public_result,
    combined: { coverage: heat.coverage || "unknown" },
    feeds: heat.feeds || [],
  };
  // Individuals and research use detections retained inside the polygon only.
  const byPlatform = {};
  (heat.inside || []).forEach((spot) => {
    const platform = spot.platform || "Unrecognized";
    if (!byPlatform[platform]) byPlatform[platform] = [];
    byPlatform[platform].push(spot);
  });
  const feedByPlatform = Object.fromEntries((heat.feeds || []).map((row) => [row.platform, row]));
  const platforms = new Set([
    ...Object.keys(byPlatform),
    ...(heat.feeds || []).map((row) => row.platform),
  ]);
  synthetic.results = [...platforms].map((platform) => {
    const hotspots = byPlatform[platform] || [];
    const feed = feedByPlatform[platform] || {};
    return {
      platform,
      status: feed.status === "unavailable"
        ? "product_unavailable"
        : feed.status === "failed"
          ? "request_failed"
          : "ok",
      coverage: heat.coverage || "unknown",
      count: hotspots.length,
      hotspots,
    };
  });
  state.lastPayload = synthetic;
  const publicResult = document.querySelector("#public-result");
  if (publicResult) publicResult.hidden = false;
  renderPublicResult(synthetic);
  renderStatuses(synthetic.results || []);
  renderAreas(synthetic.hotspot_areas);
  renderIndividuals(synthetic);
  renderResearch(synthetic);
  const center = payload.center || {};
  if (center.lat != null && center.lon != null) {
    beginPlaceLookup({ mode: "center", lat: center.lat, lon: center.lon });
  }
  openLandPanel({ tab: state.panelTab || "where", focus: false });
  updateSelectionBanner();
  drawLandCutout(synthetic.hotspot_areas.areas || []);
}

function renderFeedBreakdown(feeds) {
  if (!feeds.length) return "";
  return `<ul class="feed-breakdown">${feeds.map((row) => `
    <li class="feed-${escapeHtml(row.status || "ok")}">${escapeHtml(row.text)}</li>`).join("")}</ul>`;
}

function renderHeatGroup(title, rows, nearby = false) {
  if (!rows.length) {
    return `<p class="quiet">${nearby ? "No nearby detections within 5 km." : "No detections inside the boundary."}</p>`;
  }
  return `<h5 class="heat-group-title">${escapeHtml(title)}</h5>
    <ul class="heat-items">${rows.map((row) => `
      <li>
        <strong>${escapeHtml(row.platform)}</strong>
        · ${escapeHtml(row.acq_date || "—")} ${escapeHtml(row.acq_time || "")} UTC
        ${nearby ? `· ${Number(row.distance_km).toFixed(1)} km from boundary` : ""}
        · ${Number(row.lat).toFixed(4)}, ${Number(row.lon).toFixed(4)}
      </li>`).join("")}</ul>`;
}

function renderStatuses(results) {
  const node = document.querySelector("#statuses");
  if (!node) return;
  node.innerHTML = "";
  results.forEach((result) => {
    const card = document.createElement("article");
    card.className = `badge ${result.status}`;
    const platform = result.platform || "Request";
    card.innerHTML = `<strong>${platform}: ${STATUS_TEXT[result.status] || result.status}</strong>
      <small>${result.count || 0} detections · coverage ${result.coverage || "unknown"}${result.product ? ` · ${result.product}` : ""}</small>
      ${result.message ? `<p>${escapeHtml(result.message)}</p>` : ""}`;
    node.append(card);
  });
}

document.querySelector("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  searchPlace();
});

document.querySelector("#search").addEventListener("keydown", (event) => {
  if (event.key === "Escape") document.querySelector("#places").innerHTML = "";
});

document.addEventListener("click", (event) => {
  if (!event.target.closest("#search-form")) document.querySelector("#places").innerHTML = "";
});

document.querySelector("#change-date")?.addEventListener("click", () => {
  setHistoryView("present");
  openLandPanel({ tab: "weekly", focus: false });
  dayInput.focus();
});

document.querySelector("#draw").addEventListener("click", startPolygonDraw);
document.querySelector("#finish-draw").addEventListener("click", finishPolygonDraw);
document.querySelector("#clear-area").addEventListener("click", clearLand);
document.querySelector("#confirm").addEventListener("click", () => checkLand());
document.querySelector("#day").addEventListener("change", updateDayWords);
