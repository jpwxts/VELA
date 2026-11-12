const DEFAULT_PLATFORMS = ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"];

const state = {
  box: null,
  polygon: null,
  polygonDraft: [],
  drawing: false,
  anchor: null,
  rectangle: null,
  polygonLayer: null,
  draftLayer: null,
  forecastMarker: null,
  areaLayers: [],
  individualMarkers: [],
  selectedSquare: null,
  selectedLabel: null,
  lastPayload: null,
  lastLandCheck: null,
  multiOnly: false,
  showIndividuals: false,
  requestId: 0,
  landRequestId: 0,
  weatherRequestId: 0,
  selectedForecastDay: null,
  weeks: [],
  selectedWeek: null,
  revealed: new Map(),
  traces: null,
  forecast: null,
  selectedArea: null,
  detailRequestId: 0,
  ignoreMapClick: false,
  lastActivateToken: "",
  lastActivateAt: 0,
  memberPointLayer: null,
  markerByCell: new Map(),
  landBoundaryLabel: null,
  replayPasses: [],
  replayIndex: 0,
  replayTimer: null,
  placeName: null,
  placeRequestId: 0,
  lastPlace: null,
  panelTab: "where",
  landLabel: null,
  calendarYears: [],
  calendarEmptyReason: null,
  calendarRequestId: 0,
  savedLandSnapshot: null,
  usingSavedExample: false,
};

const INDIVIDUAL_COLORS = {
  Aqua: "#d4551a",
  Terra: "#8a4b32",
  "Suomi-NPP": "#1f6f8b",
  "NOAA-20": "#1e5a45",
  "NOAA-21": "#6d4b86",
  Unrecognized: "#55504b",
};

const STATUS_TEXT = {
  ok: "Detections returned",
  no_hotspots: "No hotspots returned",
  product_unavailable: "Unavailable for this date",
  request_failed: "Request failed",
  not_configured: "Map key needed",
  area_too_large: "Area too large",
  none_selected: "Select a platform",
};

const map = L.map("map", { worldCopyJump: true, zoomControl: true }).setView([-14, -50.5], 3);
const traceLayer = L.layerGroup().addTo(map);
L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
  attribution: 'Tiles © Esri · Places © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
  maxZoom: 12,
}).addTo(map);

const legend = L.control({ position: "topright" });
legend.onAdd = () => {
  const node = L.DomUtil.create("div", "legend");
  node.innerHTML = `
    <div><span class="heat-wave" style="width:14px;height:14px;display:inline-grid;place-items:center;vertical-align:-2px;margin-right:6px;border-radius:50%"><span class="heat-wave-icon" aria-hidden="true">♨</span></span>Heat · 1 sat</div>
    <div style="margin-top:4px"><span class="heat-wave" style="width:14px;height:14px;display:inline-grid;place-items:center;vertical-align:-2px;margin-right:6px;border-radius:4px;background:#c2410c"><span class="heat-wave-icon" aria-hidden="true">♨</span></span>Heat · 2+ sats</div>
    <p class="legend-note">Grouped in 5 km squares. Not a wildfire count.</p>`;
  return node;
};
legend.addTo(map);

const dayInput = document.querySelector("#day");
const today = new Date();
today.setDate(today.getDate() - 7);
dayInput.value = today.toISOString().slice(0, 10);
document.querySelector("#year").value = today.getUTCFullYear();
updateDayWords();

document.querySelector("#search-button").addEventListener("click", searchPlace);
document.querySelector("#search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") searchPlace();
});
document.querySelector("#try-example").addEventListener("click", loadCompetitionDemo);
document.querySelector("#draw").addEventListener("click", startPolygonDraw);
document.querySelector("#finish-draw").addEventListener("click", finishPolygonDraw);
document.querySelector("#clear-area").addEventListener("click", clearLand);
document.querySelector("#confirm").addEventListener("click", () => checkLand());
document.querySelector("#day").addEventListener("change", updateDayWords);
document.querySelector("#see-where")?.addEventListener("click", () => openLandPanel({ tab: "where" }));
document.querySelector("#show-individuals").addEventListener("change", (event) => {
  state.showIndividuals = event.target.checked;
  renderIndividuals(state.lastPayload);
});
document.querySelector("#sheet-close").addEventListener("click", closeAreaPanel);
document.querySelector("#copy-coords")?.addEventListener("click", copyPlaceCoordinates);
document.querySelector("#year").addEventListener("change", loadCalendar);
document.querySelector("#export").addEventListener("click", (event) => {
  if (!state.box) {
    event.preventDefault();
    return;
  }
  const year = document.querySelector("#year").value;
  const [west, south, east, north] = state.box;
  event.currentTarget.href = `/api/export.csv?west=${west}&south=${south}&east=${east}&north=${north}&year=${year}`;
});
document.querySelector("#trace")?.addEventListener("click", showTrace);
document.querySelector("#trace-detail")?.addEventListener("click", (event) => {
  const choice = event.target.closest(".trace-choice");
  if (!choice) return;
  renderTrace(choice.dataset.outcome);
});
document.querySelector("#week-detail")?.addEventListener("click", (event) => {
  const choice = event.target.closest(".trace-choice");
  if (!choice) return;
  renderTrace(choice.dataset.outcome);
});
document.querySelectorAll(".panel-tab").forEach((button) => {
  button.addEventListener("click", () => switchPanelTab(button.dataset.panelTab));
  button.addEventListener("keydown", (event) => {
    const tabs = [...document.querySelectorAll(".panel-tab")];
    const index = tabs.indexOf(button);
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const next = event.key === "ArrowRight"
        ? tabs[(index + 1) % tabs.length]
        : tabs[(index - 1 + tabs.length) % tabs.length];
      next.focus();
      switchPanelTab(next.dataset.panelTab);
    } else if (event.key === "Home") {
      event.preventDefault();
      tabs[0].focus();
      switchPanelTab(tabs[0].dataset.panelTab);
    } else if (event.key === "End") {
      event.preventDefault();
      tabs[tabs.length - 1].focus();
      switchPanelTab(tabs[tabs.length - 1].dataset.panelTab);
    }
  });
});
document.querySelector("#try-zambia")?.addEventListener("click", loadZambiaWeeklyExample);
document.querySelector("#return-selection")?.addEventListener("click", restoreSavedLandSelection);
document.querySelector("#open-weather-tab")?.addEventListener("click", () => switchPanelTab("weather"));
if (document.querySelector("#try-zambia")) document.querySelector("#try-zambia").hidden = false;

map.on("click", async (event) => {
  if (state.ignoreMapClick) return;
  if (state.drawing) {
    addPolygonVertex(event.latlng);
    return;
  }
  if (!state.box || !state.lastPayload) return;
  await askAboutPoint(event.latlng.lat, event.latlng.lng);
});

document.querySelector("#show-detected-areas")?.addEventListener("click", () => {
  closeAreaPanel();
  if (state.lastPayload?.hotspot_areas?.areas?.length) {
    const first = state.lastPayload.hotspot_areas.areas[0];
    map.fitBounds([
      [first.bounds.south, first.bounds.west],
      [first.bounds.north, first.bounds.east],
    ], { maxZoom: 8, padding: [24, 24] });
  }
});

document.querySelector("#weather-retry")?.addEventListener("click", () => loadWeatherOutlook({ retry: true }));

const bootFixture = new URLSearchParams(location.search).get("fixture");
if (bootFixture === "click_regression" || bootFixture === "two_satellites") {
  loadClickFixture(bootFixture);
} else if (bootFixture === "check_land_demo") {
  loadCompetitionDemo();
} else if (bootFixture === "weather_outlook_amazon" || bootFixture === "weather_values_missing" || bootFixture === "weather_no_fwi") {
  loadStatus();
  loadWeatherFixture(bootFixture);
} else {
  loadStatus();
}

document.querySelector("#replay-prev")?.addEventListener("click", () => stepReplay(-1));
document.querySelector("#replay-next")?.addEventListener("click", () => stepReplay(1));
document.querySelector("#replay-play")?.addEventListener("click", toggleReplay);
document.querySelector("#view-fire-calendar")?.addEventListener("click", () => {
  if (state.selectedArea?.observation_day) {
    document.querySelector("#year").value = state.selectedArea.observation_day.slice(0, 4);
  }
  switchPanelTab("weekly");
});

async function loadClickFixture(name = "click_regression") {
  const response = await fetch(`/api/hotspots/fixture?name=${encodeURIComponent(name)}`);
  const payload = await response.json();
  const box = payload.bbox || { west: -50.3, south: -14.3, east: -49.7, north: -13.7 };
  setBox([box.west, box.south, box.east, box.north], payload.fixture?.label || "Hotspot fixture");
  dayInput.value = payload.date;
  updateDayWords();
  document.querySelectorAll(".satellite-details fieldset input").forEach((node) => {
    node.checked = ["NOAA-20", "Aqua", "Suomi-NPP", "NOAA-21"].includes(node.value);
  });
  renderHotspots(payload);
  const status = document.querySelector("#result-status");
  if (status) {
    status.hidden = false;
    status.textContent = payload.fixture?.label || "Hotspot fixture";
  }
  const banner = document.querySelector("#fixture-banner");
  if (banner) {
    banner.hidden = false;
    banner.textContent = payload.fixture?.label || "Hotspot fixture";
  }
}

function switchView(name) {
  // Legacy alias: weather fixtures used to leave the map page.
  const tab = name === "hotspots" ? "where" : name === "weekly" ? "weekly" : name === "research" ? "research" : "weather";
  openLandPanel({ tab });
}

function switchPanelTab(name) {
  const tabName = name || "where";
  state.panelTab = tabName;
  let activeTab = null;
  document.querySelectorAll(".panel-tab").forEach((node) => {
    const on = node.dataset.panelTab === tabName;
    node.classList.toggle("on", on);
    node.setAttribute("aria-selected", on ? "true" : "false");
    node.tabIndex = on ? 0 : -1;
    if (on) activeTab = node;
  });
  document.querySelectorAll(".panel-pane").forEach((node) => {
    node.hidden = node.id !== `pane-${tabName}`;
  });
  activeTab?.scrollIntoView({ inline: "nearest", block: "nearest", behavior: "smooth" });
  if (tabName === "weather") loadWeatherOutlook();
  if (tabName === "weekly") loadCalendar();
  if (tabName === "research") renderResearch(state.lastPayload);
}

function openLandPanel(options = {}) {
  const panel = document.querySelector("#area-panel");
  panel.hidden = false;
  updateSelectionBanner();
  switchPanelTab(options.tab || state.panelTab || "where");
  if (options.focus !== false) panel.focus({ preventScroll: true });
}

function updateSelectionBanner() {
  const place = document.querySelector("#selection-place");
  const boundary = document.querySelector("#selection-boundary");
  const placeText =
    state.lastPlace?.label
    || state.placeName
    || state.landLabel
    || (state.selectedArea ? `Selected 5 km cell ${state.selectedArea.cell_id}` : null)
    || "Selected land";
  place.textContent = placeText;
  if (state.box) {
    const [west, south, east, north] = state.box;
    const corners = state.polygon ? Math.max(0, state.polygon.length - 1) : 4;
    boundary.textContent = state.polygon
      ? `${corners} corners · west ${west}, south ${south}, east ${east}, north ${north}`
      : `West ${west}, south ${south}, east ${east}, north ${north}`;
  } else {
    boundary.textContent = "Draw or select land to explore weather, weekly trends, and research.";
  }
}

function updateDayWords() {
  const node = document.querySelector("#day-words");
  const value = dayInput.value;
  if (!value) {
    node.textContent = "Choose a date.";
    return;
  }
  node.textContent = formatObservationDay(value);
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
      "A square observed on Monday and Tuesday counts twice, once for each day. The value measures activity frequency; burned area and the number of separate fires are different measurements.";
  }
  const researchMetric = document.querySelector("#metric-research");
  if (researchMetric) researchMetric.textContent = payload.metric;
}

async function searchPlace() {
  const query = document.querySelector("#search").value.trim();
  const list = document.querySelector("#places");
  list.innerHTML = "";
  if (query.length < 2) return;
  const response = await fetch(`/api/geocode?q=${encodeURIComponent(query)}`);
  if (!response.ok) {
    list.innerHTML = "<li>Place search failed. Draw a rectangle instead.</li>";
    return;
  }
  const payload = await response.json();
  payload.places.forEach((place) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = place.name;
    button.addEventListener("click", () => {
      state.placeName = place.name;
      setBox([place.west, place.south, place.east, place.north], place.name);
      // Place search starts from a rectangle visitors can edit into a tighter plot.
      setPolygonFromBox(state.box, place.name);
    });
    item.append(button);
    list.append(item);
  });
  if (!payload.places.length) list.innerHTML = "<li>No matching place.</li>";
}

function setBox(box, label) {
  state.box = box.map((value) => Number(Number(value).toFixed(4)));
  const [west, south, east, north] = state.box;
  clearRectangle();
  const parts = west <= east ? [[west, east]] : [[west, 180], [-180, east]];
  // Ember orange search/land boundary — distinct from Orbit teal cell selection.
  state.rectangle = parts.map(([left, right]) => L.rectangle([[south, left], [north, right]], {
    color: "#d4551a",
    weight: 2,
    dashArray: "6 4",
    fillColor: "#e8590c",
    fillOpacity: 0.04,
    interactive: false,
  }).addTo(map));
  if (state.landBoundaryLabel) {
    map.removeLayer(state.landBoundaryLabel);
    state.landBoundaryLabel = null;
  }
  state.landBoundaryLabel = L.marker([north, (west + east) / 2], {
    icon: L.divIcon({
      className: "",
      html: `<div class="land-boundary-label">Search boundary</div>`,
      iconSize: [120, 20],
      iconAnchor: [60, 22],
    }),
    interactive: false,
  }).addTo(map);
  const bounds = L.latLngBounds(state.rectangle.map((layer) => layer.getBounds()));
  map.fitBounds(bounds, { padding: [24, 24], maxZoom: 8 });
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
  state.polygonLayer = L.polygon(ring.map(([lon, lat]) => [lat, lon]), {
    color: "#d4551a",
    weight: 3,
    fillColor: "#e8590c",
    fillOpacity: 0.12,
    // Fill must not steal taps meant for heat markers underneath.
    interactive: false,
  }).addTo(map);
  map.fitBounds(state.polygonLayer.getBounds(), { padding: [28, 28], maxZoom: 11 });
  document.querySelector("#area-label").textContent =
    `${label || "Your land"}. ${ring.length - 1} corners. You can redraw after checking.`;
  document.querySelector("#map-hint").textContent = "Boundary selected. Tap Check my land.";
  clearWeatherOutlook();
}

function clearRectangle() {
  if (state.rectangle) {
    const layers = Array.isArray(state.rectangle) ? state.rectangle : [state.rectangle];
    layers.forEach((layer) => map.removeLayer(layer));
    state.rectangle = null;
  }
  if (state.landBoundaryLabel) {
    map.removeLayer(state.landBoundaryLabel);
    state.landBoundaryLabel = null;
  }
}

function clearPolygonLayers() {
  if (state.polygonLayer) {
    map.removeLayer(state.polygonLayer);
    state.polygonLayer = null;
  }
  if (state.draftLayer) {
    map.removeLayer(state.draftLayer);
    state.draftLayer = null;
  }
}

function clearForecastMarker() {
  if (state.forecastMarker) {
    map.removeLayer(state.forecastMarker);
    state.forecastMarker = null;
  }
}

function clearLand() {
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
  document.querySelector("#finish-draw").hidden = true;
  document.querySelector("#area-label").textContent = "Search or draw a plot boundary, then check your land.";
  document.querySelector("#map-hint").textContent = "Draw your land, then tap Check my land.";
  resetLandResult();
  clearWeatherOutlook();
}

function clearWeatherOutlook() {
  renderOutlook(null, weatherSelectors());
  const location = document.querySelector("#weather-location");
  if (location) {
    location.textContent =
      "Confirm land on the My land view to load a seven-day outlook near the center of your plot.";
  }
  const banner = document.querySelector("#weather-fixture-banner");
  if (banner) banner.hidden = true;
  const retry = document.querySelector("#weather-retry");
  if (retry) retry.hidden = true;
}

function startPolygonDraw() {
  state.drawing = true;
  state.polygonDraft = [];
  clearPolygonLayers();
  document.querySelector("#finish-draw").hidden = false;
  document.querySelector("#area-label").textContent =
    "Click corners of your plot. Tap Finish boundary when the shape is closed enough.";
  document.querySelector("#map-hint").textContent = "Drawing land boundary…";
}

function addPolygonVertex(latlng) {
  state.polygonDraft.push([latlng.lng, latlng.lat]);
  if (state.draftLayer) map.removeLayer(state.draftLayer);
  const latlngs = state.polygonDraft.map(([lon, lat]) => [lat, lon]);
  state.draftLayer = L.polyline(latlngs, { color: "#d4551a", weight: 2, dashArray: "6 4" }).addTo(map);
  state.polygonDraft.forEach(([lon, lat]) => {
    L.circleMarker([lat, lon], { radius: 4, color: "#9a3412", fillOpacity: 1 }).addTo(state.draftLayer);
  });
  document.querySelector("#area-label").textContent =
    `${state.polygonDraft.length} corner${state.polygonDraft.length === 1 ? "" : "s"} placed. Finish when ready.`;
}

function finishPolygonDraw() {
  if (state.polygonDraft.length < 3) {
    document.querySelector("#area-label").textContent = "Add at least three corners before finishing.";
    return;
  }
  state.drawing = false;
  document.querySelector("#finish-draw").hidden = true;
  setPolygon(state.polygonDraft, "Drawn land");
  state.polygonDraft = [];
  if (state.draftLayer) {
    map.removeLayer(state.draftLayer);
    state.draftLayer = null;
  }
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
  document.querySelector("#see-where").hidden = true;
  document.querySelector("#weather-headline").textContent = "Checking your land…";
  document.querySelector("#weather-explanation").textContent =
    "Loading the fire-danger outlook and recent satellite heat.";
  document.querySelector("#weather-status").textContent = "Loading…";
}

async function loadCompetitionDemo() {
  setDefaultPlatforms();
  const requestId = ++state.landRequestId;
  resetLandResult();
  document.querySelector("#fixture-banner").hidden = false;
  document.querySelector("#fixture-banner").textContent = "Loading saved competition demo…";
  document.querySelector("#area-label").textContent = "Loading labeled demo boundary and archived forecast…";
  try {
    const response = await fetch("/api/check-land/fixture?name=check_land_demo");
    const payload = await response.json();
    if (requestId !== state.landRequestId) return;
    const ring = payload.polygon?.coordinates?.[0] || [];
    dayInput.value = payload.observation_date || dayInput.value;
    updateDayWords();
    setPolygon(ring, payload.label || "Competition example");
    renderLandCheck(payload);
  } catch (error) {
    if (requestId !== state.landRequestId) return;
    document.querySelector("#fixture-banner").hidden = false;
    document.querySelector("#fixture-banner").textContent = "Demo fixture failed to load.";
  }
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
  state.landLabel = options.label || "Your land";
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
    document.querySelector("#weather-headline").textContent = "The land check failed.";
    document.querySelector("#weather-explanation").textContent = "Check your connection and try again.";
    document.querySelector("#weather-status").textContent = "Retry with Check my land.";
  }
}

function setResultLead(text) {
  const node = document.querySelector("#result-lead");
  if (node) node.textContent = text;
}

function renderLandCheck(payload) {
  state.lastLandCheck = payload;
  state.forecast = payload.forecast || null;
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
    state.forecastMarker = L.circleMarker([point.latitude, point.longitude], {
      radius: 6,
      color: "#1e5a45",
      weight: 2,
      fillColor: "#fffdf9",
      fillOpacity: 1,
    }).addTo(map);
    state.forecastMarker.bindTooltip("Forecast near the center of your plot", { permanent: false });
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
  const seeWhere = document.querySelector("#see-where");
  seeWhere.hidden = !((heat.inside || []).length || (heat.nearby || []).length);
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
  return `<h3 class="heat-group-title">${escapeHtml(title)}</h3>
    <ul class="heat-items">${rows.map((row) => `
      <li>
        <strong>${escapeHtml(row.platform)}</strong>
        · ${escapeHtml(row.acq_date || "—")} ${escapeHtml(row.acq_time || "")} UTC
        ${nearby ? `· ${Number(row.distance_km).toFixed(1)} km from boundary` : ""}
        · ${Number(row.lat).toFixed(4)}, ${Number(row.lon).toFixed(4)}
      </li>`).join("")}</ul>`;
}

function formatShortForecastDay(day) {
  if (!day) return "—";
  const [year, month, dayNumber] = String(day).split("-").map(Number);
  if (!year || !month || !dayNumber) return String(day);
  const date = new Date(Date.UTC(year, month - 1, dayNumber));
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

function fieldLine(label, field, unit) {
  if (!field || field.status === "missing" || field.value == null) {
    return `<li><strong>${escapeHtml(label)}</strong> · missing</li>`;
  }
  const value = Number(field.value);
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `<li><strong>${escapeHtml(label)}</strong> · ${text} ${escapeHtml(unit)}</li>`;
}

function dayCardSummary(day) {
  if (day.danger_level) return day.danger_level;
  const temp = day.temperature_max_c || {};
  if (temp.status !== "missing" && temp.value != null) {
    return `${Number(temp.value).toFixed(0)}°C`;
  }
  const rain = day.forecast_rain_mm || {};
  if (rain.status !== "missing" && rain.value != null) {
    return `${Number(rain.value).toFixed(1)} mm`;
  }
  return "No values";
}

function renderOutlook(forecast, selectors) {
  const headline = document.querySelector(selectors.headline);
  const explanation = document.querySelector(selectors.explanation);
  const coverage = document.querySelector(selectors.coverage);
  const status = document.querySelector(selectors.status);
  const daysHost = document.querySelector(selectors.days);
  const detail = document.querySelector(selectors.detail);
  const meta = document.querySelector(selectors.meta);
  const retry = selectors.retry ? document.querySelector(selectors.retry) : null;
  const fixtureBanner = selectors.fixtureBanner ? document.querySelector(selectors.fixtureBanner) : null;

  state.forecast = forecast || null;
  const point = forecast?.point || {};
  const valuesAvailable = forecast?.values_available !== false && (forecast?.days || []).some((day) => {
    const fire = day.fire_danger || {};
    return (
      (fire.status === "measured" && fire.fwi != null) ||
      ["temperature_max_c", "forecast_rain_mm", "wind_speed_max_m_s", "relative_humidity_min_percent"].some((key) => {
        const field = day[key] || {};
        return field.status !== "missing" && field.value != null;
      })
    );
  });

  if (fixtureBanner) {
    if (forecast?.fixture?.label || forecast?.saved) {
      fixtureBanner.hidden = false;
      fixtureBanner.textContent = forecast.fixture?.label || "Saved weather fixture";
    } else {
      fixtureBanner.hidden = true;
    }
  }

  if (!forecast || !(forecast.days || []).length) {
    headline.textContent = "Forecast values unavailable";
    explanation.textContent = "No outlook days were returned for this location.";
    coverage.textContent = "";
    status.textContent = "";
    daysHost.innerHTML = "";
    detail.hidden = true;
    if (meta) meta.innerHTML = "";
    if (retry) retry.hidden = false;
    return;
  }

  if (!valuesAvailable) {
    headline.textContent = "Forecast values unavailable";
    explanation.textContent =
      forecast.headline_explanation ||
      "Dates were returned, but temperature, rainfall, wind, and fire-danger measurements are missing.";
    coverage.textContent = forecast.coverage?.text || "";
    status.textContent = forecast.forecast_status?.text || "";
    daysHost.innerHTML = (forecast.days || [])
      .map(
        (day) =>
          `<button type="button" class="day-chip" disabled><strong>No values</strong><span>${escapeHtml(formatShortForecastDay(day.valid_date))}</span></button>`
      )
      .join("");
    detail.hidden = true;
    if (retry) retry.hidden = false;
    if (meta) {
      meta.innerHTML = outlookMetaHtml(forecast, point);
    }
    return;
  }

  if (retry) retry.hidden = true;
  headline.textContent = forecast.headline || "Weather outlook";
  explanation.textContent = forecast.headline_explanation || "";
  coverage.textContent = forecast.coverage?.text || "Forecast near the center of your plot.";
  status.textContent = forecast.forecast_status?.text || "";

  daysHost.innerHTML = "";
  (forecast.days || []).forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day-chip";
    button.dataset.date = day.valid_date;
    button.setAttribute("role", "listitem");
    button.innerHTML = `<strong>${escapeHtml(dayCardSummary(day))}</strong><span>${escapeHtml(formatShortForecastDay(day.valid_date))}</span>`;
    if (day.valid_date === forecast.attention_day) button.classList.add("peak");
    button.addEventListener("click", () => showOutlookDay(day, forecast, selectors));
    daysHost.append(button);
  });

  if (meta) meta.innerHTML = outlookMetaHtml(forecast, point);

  const selected =
    (forecast.days || []).find((day) => day.valid_date === state.selectedForecastDay) ||
    forecast.peak_day ||
    (forecast.days || []).find((day) => day.valid_date === forecast.attention_day) ||
    forecast.days[0];
  if (selected) showOutlookDay(selected, forecast, selectors);
}

function outlookMetaHtml(forecast, point) {
  return `
    <p><strong>Location</strong> · Forecast near the center of your plot${
      point.latitude != null
        ? ` (${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)})`
        : ""
    }</p>
    <p><strong>Sources</strong> · Open-Meteo weather · Copernicus GWIS ECMWF Fire Weather Index</p>
    <p><strong>Units</strong> · °C, %, m/s, mm · FWI is a unitless index · ranking is a local historical percentile</p>
    <p><strong>Grid</strong> · about ${escapeHtml(String(forecast.grid_resolution_km || 8))} km GWIS cells</p>
    <p><strong>Timing</strong> · ${escapeHtml(forecast.forecast_status?.text || "Issue time unavailable")}</p>
    <p><strong>Class table</strong> · ${escapeHtml(forecast.danger_class_source || "GWIS Fire Danger Classes")}</p>`;
}

function showOutlookDay(day, forecast, selectors) {
  const detail = document.querySelector(selectors.detail);
  const daysHost = document.querySelector(selectors.days);
  state.selectedForecastDay = day.valid_date;
  detail.hidden = false;
  const fire = day.fire_danger || {};
  const fwiText =
    fire.status === "measured" && fire.fwi != null
      ? `${Number(fire.fwi).toFixed(1)} (GWIS class: ${day.danger_level || "unclassified"})`
      : "missing";
  const rankingText = fire.ranking == null ? "missing" : Number(fire.ranking).toFixed(1);
  detail.innerHTML = `
    <h3>${escapeHtml(formatShortForecastDay(day.valid_date))}${
      day.danger_level ? ` · ${escapeHtml(day.danger_level)} fire danger` : ""
    }</h3>
    <p>${escapeHtml(day.explanation || "")}</p>
    <ul class="outlook-measures">
      ${fieldLine("Maximum temperature", day.temperature_max_c, "°C")}
      ${fieldLine("Minimum relative humidity", day.relative_humidity_min_percent, "%")}
      ${fieldLine("Maximum wind speed", day.wind_speed_max_m_s, "m/s")}
      ${fieldLine("Forecast rainfall", day.forecast_rain_mm, "mm")}
      <li><strong>Fire Weather Index</strong> · ${escapeHtml(fwiText)}</li>
      <li><strong>Local historical ranking</strong> · ${escapeHtml(rankingText)}</li>
    </ul>`;
  daysHost.querySelectorAll(".day-chip").forEach((node) => {
    node.classList.toggle("on", node.dataset.date === day.valid_date);
  });
}

function forecastHasUsefulValues(forecast) {
  return Boolean(
    forecast
    && (forecast.days || []).some((day) => {
      const fire = day.fire_danger || {};
      return (
        (fire.status === "measured" && fire.fwi != null)
        || ["temperature_max_c", "forecast_rain_mm", "wind_speed_max_m_s", "relative_humidity_min_percent"].some((key) => {
          const field = day[key] || {};
          return field.status !== "missing" && field.value != null;
        })
      );
    })
  );
}

async function loadWeatherOutlook(options = {}) {
  const location = document.querySelector("#weather-location");
  const retry = document.querySelector("#weather-retry");
  if (!state.box) {
    renderOutlook(null, weatherSelectors());
    location.textContent = "Confirm land on the My land view to load a seven-day outlook near the center of your plot.";
    if (retry) retry.hidden = true;
    return;
  }
  const cached =
    state.forecast
    || state.lastLandCheck?.forecast
    || state.lastPayload?.forecast
    || null;
  const preferCached =
    !options.retry
    && cached
    && (cached.saved || cached.fixture || forecastHasUsefulValues(cached));
  if (preferCached) {
    applyWeatherOutlook(cached);
    return;
  }
  const [west, south, east, north] = state.box;
  const requestId = ++state.weatherRequestId;
  location.textContent = `Loading outlook near the center of your plot (${west}, ${south} to ${east}, ${north})…`;
  document.querySelector("#weather-headline").textContent = "Loading forecast…";
  document.querySelector("#weather-explanation").textContent =
    "An older response will not replace this outlook.";
  try {
    const response = await fetch(
      `/api/preparedness?west=${west}&south=${south}&east=${east}&north=${north}`
    );
    const payload = await response.json();
    if (requestId !== state.weatherRequestId) return;
    applyWeatherOutlook(payload);
  } catch (error) {
    if (requestId !== state.weatherRequestId) return;
    renderOutlook(null, weatherSelectors());
    document.querySelector("#weather-headline").textContent = "Forecast values unavailable";
    document.querySelector("#weather-explanation").textContent = "The forecast request failed.";
    if (retry) retry.hidden = false;
  }
}

async function loadWeatherFixture(name) {
  switchView("weather");
  const requestId = ++state.weatherRequestId;
  try {
    const response = await fetch(`/api/preparedness/fixture?name=${encodeURIComponent(name)}`);
    const payload = await response.json();
    if (requestId !== state.weatherRequestId) return;
    if (payload.bbox) {
      const box = payload.bbox;
      setBox([box.west, box.south, box.east, box.north], payload.fixture?.label || "Weather fixture area");
      setPolygonFromBox(state.box, payload.fixture?.label || "Weather fixture area");
    }
    applyWeatherOutlook(payload);
  } catch (error) {
    if (requestId !== state.weatherRequestId) return;
    document.querySelector("#weather-headline").textContent = "Forecast values unavailable";
    document.querySelector("#weather-explanation").textContent = "Weather fixture failed to load.";
  }
}

function weatherSelectors() {
  return {
    headline: "#weather-headline",
    explanation: "#weather-explanation",
    coverage: "#weather-coverage",
    status: "#weather-status",
    days: "#weather-days",
    detail: "#weather-detail",
    meta: "#weather-meta-body",
    retry: "#weather-retry",
    fixtureBanner: "#weather-fixture-banner",
  };
}

function applyWeatherOutlook(payload) {
  state.selectedForecastDay = null;
  const point = payload.point || {};
  const issued = payload.issued_at || payload.archive_time || null;
  const days = payload.days || [];
  const firstDate = days[0]?.valid_date;
  const lastDate = days[days.length - 1]?.valid_date;
  const obsDate = document.querySelector("#date")?.value || document.querySelector('input[type="date"]')?.value || "";
  let locationText = "Forecast near the center of your plot.";
  if (point.latitude != null && point.longitude != null) {
    locationText =
      `This outlook is a point forecast near the center of the selected land `
      + `(${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)}).`;
  }
  if (firstDate && lastDate) {
    locationText += ` Outlook covers ${formatObservationDay(firstDate)} to ${formatObservationDay(lastDate)}.`;
  }
  if (issued) {
    locationText += ` Issued/archived ${formatObservationDay(String(issued).slice(0, 10))}.`;
  }
  if (obsDate && firstDate && obsDate < firstDate) {
    locationText +=
      ` You are viewing historical satellite heat from ${formatObservationDay(obsDate)}; the forecast dates above are current outlook dates, not that past day.`;
  }
  document.querySelector("#weather-location").textContent = locationText;
  renderOutlook(payload, weatherSelectors());
  const researchPerf = document.querySelector("#research-performance");
  if (researchPerf) {
    researchPerf.textContent = `Harmonization validation: ${(payload.performance || {}).text || "Pending verification."}`;
  }
}

function highlightLandHeat() {
  const heat = state.lastLandCheck?.heat;
  if (!heat) return;
  clearMemberPoints();
  state.memberPointLayer = L.layerGroup().addTo(map);
  const points = [...(heat.inside || []), ...(heat.nearby || [])];
  points.forEach((spot) => {
    const marker = L.circleMarker([spot.lat, spot.lon], {
      radius: spot.relation === "inside" ? 7 : 6,
      color: "#fffdf9",
      weight: 2,
      fillColor: spot.relation === "inside" ? "#d4551a" : "#1f6f8b",
      fillOpacity: 1,
    });
    marker.bindTooltip(
      `${spot.platform} · ${spot.acq_time || ""} UTC · ${spot.relation}${spot.relation === "nearby" ? ` · ${spot.distance_km} km` : ""}`,
      { sticky: true }
    );
    marker.addTo(state.memberPointLayer);
  });
  if (points.length) {
    map.fitBounds(L.latLngBounds(points.map((spot) => [spot.lat, spot.lon])), {
      padding: [40, 40],
      maxZoom: 12,
    });
  }
}

function clearMapLayers() {
  state.areaLayers.forEach((layer) => map.removeLayer(layer));
  state.areaLayers = [];
  state.markerByCell.clear();
  state.individualMarkers.forEach((marker) => map.removeLayer(marker));
  state.individualMarkers = [];
  clearSelectedSquare();
  clearMemberPoints();
}

function clearMemberPoints() {
  if (state.memberPointLayer) {
    map.removeLayer(state.memberPointLayer);
    state.memberPointLayer = null;
  }
}

function clearSelectedSquare() {
  if (state.selectedSquare) map.removeLayer(state.selectedSquare);
  if (state.selectedLabel) map.removeLayer(state.selectedLabel);
  state.selectedSquare = null;
  state.selectedLabel = null;
}

function guardMapClick() {
  state.ignoreMapClick = true;
  window.setTimeout(() => {
    state.ignoreMapClick = false;
  }, 400);
}

function areaContainingPoint(lat, lon, areas) {
  return (areas || []).find((area) => {
    const bounds = area.bounds || {};
    return (
      lat >= bounds.south &&
      lat <= bounds.north &&
      lon >= bounds.west &&
      lon <= bounds.east
    );
  });
}

function visibleAreas(hotspotAreas) {
  const areas = (hotspotAreas && hotspotAreas.areas) || [];
  if (!state.multiOnly) return areas;
  return areas.filter((area) => area.multiple_satellites);
}

function renderHotspots(payload) {
  state.lastPayload = payload;
  state.multiOnly = false;
  clearMapLayers();
  const publicResult = document.querySelector("#public-result");
  if (publicResult) publicResult.hidden = false;
  renderPublicResult(payload);
  renderStatuses(payload.results || []);
  renderAreas(payload.hotspot_areas);
  renderIndividuals(payload);
  renderResearch(payload);
}

function applyAreaFilter(multiOnly) {
  state.multiOnly = Boolean(multiOnly);
  closeAreaPanel();
  clearMapLayers();
  renderPublicResult(state.lastPayload);
  renderAreas(state.lastPayload?.hotspot_areas);
  renderIndividuals(state.lastPayload);
}

function renderPublicResult(payload) {
  const lead = document.querySelector("#result-lead");
  const multi = document.querySelector("#result-multi");
  const support = document.querySelector("#result-support");
  const filterHost = document.querySelector("#result-filter");
  if (!payload) {
    lead.textContent = "Choose a place and date, then show hotspots.";
    multi.textContent = "";
    support.textContent = "";
    filterHost.hidden = true;
    filterHost.innerHTML = "";
    return;
  }
  const areas = payload.hotspot_areas || {};
  const publicResult = payload.public_result || {};
  const total = Number(areas.area_count || 0);
  const multiCount = Number(areas.multiple_satellite_area_count || 0);
  const detections = Number(areas.detection_count || 0);
  const selected = selectedPlatforms();

  if (publicResult.kind === "unknown_empty") {
    lead.textContent = publicResult.text || publicResult.lead;
    multi.textContent = "";
    support.textContent = "Missing detections are not the same as no heat.";
    filterHost.hidden = true;
    filterHost.innerHTML = "";
    maybeCompareButton(filterHost, selected);
    return;
  }

  if (state.multiOnly) {
    const shown = visibleAreas(payload.hotspot_areas).length;
    lead.textContent = shown
      ? `Showing ${shown} of ${total} areas`
      : `All ${total} areas are hidden by the current filter.`;
    multi.textContent = "";
    support.textContent = shown
      ? `${detections} individual satellite detection${detections === 1 ? "" : "s"} remain accessible.`
      : "Turn off the filter to restore hotspot markers.";
  } else if (multiCount === 0 && total > 0) {
    lead.textContent = `Satellites detected heat in ${total} areas. Each area was reported by one satellite.`;
    multi.textContent = "";
    support.textContent = `${detections} satellite detection${detections === 1 ? "" : "s"} in total.`;
  } else {
    lead.textContent = publicResult.lead || `Satellites detected heat in ${total} areas.`;
    multi.textContent = publicResult.multi_line || "";
    support.textContent = `${detections} individual satellite detection${detections === 1 ? "" : "s"} remain accessible.`;
  }

  filterHost.hidden = false;
  filterHost.innerHTML = "";
  if (state.multiOnly) {
    const status = document.createElement("p");
    status.className = "filter-status";
    status.textContent = `Showing ${multiCount} of ${total} areas.`;
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "filter-button";
    clear.textContent = `Show all ${total} areas`;
    clear.addEventListener("click", () => applyAreaFilter(false));
    filterHost.append(status, clear);
  } else if (multiCount > 0) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "filter-button";
    button.textContent = `Show those ${multiCount} areas`;
    button.setAttribute("aria-label", `Show areas seen by more than one satellite (${multiCount})`);
    button.addEventListener("click", () => applyAreaFilter(true));
    filterHost.append(button);
  }
  maybeCompareButton(filterHost, selected);
  if (!filterHost.children.length) filterHost.hidden = true;
}

function maybeCompareButton(host, selected) {
  if (selected.length !== 1) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "filter-button";
  button.textContent = "Compare all satellites";
  button.addEventListener("click", () => checkLand({ label: "Your land" }));
  host.hidden = false;
  host.append(button);
}

function heatIcon(area, selected) {
  const count = Number(area.satellite_count || 1);
  const label = count === 1 ? "1 sat" : `${count} sats`;
  const multi = count > 1;
  const className = `heat-marker${multi ? " multi" : ""}${selected ? " selected" : ""}`;
  const aria = `Heat detected by ${count} satellite${count === 1 ? "" : "s"}`;
  return L.divIcon({
    className: "heat-div-icon",
    html: `<div class="${className}" role="img" aria-label="${aria}"><span class="heat-wave"><span class="heat-wave-icon" aria-hidden="true">♨</span></span><span class="sat-badge">${label}</span></div>`,
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  });
}

function activateArea(area, event) {
  if (event) {
    L.DomEvent.stopPropagation(event);
    if (event.originalEvent) L.DomEvent.preventDefault(event);
  }
  // touchend + synthesized click can both arrive; keep one open for this cell.
  const token = `${area?.cell_id || ""}:${area?.observation_day || ""}`;
  const now = Date.now();
  if (token && token === state.lastActivateToken && now - state.lastActivateAt < 400) {
    guardMapClick();
    return;
  }
  state.lastActivateToken = token;
  state.lastActivateAt = now;
  guardMapClick();
  showArea(area);
}

function areaForMarker(marker, fallback) {
  const cellId = marker?.options?.velaAreaId || fallback?.cell_id;
  return (
    (state.lastPayload?.hotspot_areas?.areas || []).find((item) => item.cell_id === cellId) ||
    fallback
  );
}

function bindHeatMarkerInteractions(marker, area) {
  const element = marker.getElement();
  if (!element) return;
  L.DomEvent.disableClickPropagation(element);
  L.DomEvent.disableScrollPropagation(element);
  const openFromDom = (domEvent) => {
    domEvent.stopPropagation();
    domEvent.preventDefault();
    activateArea(areaForMarker(marker, area), { originalEvent: domEvent });
  };
  // Capture-phase click/touch so the map's empty-square handler never wins.
  element.addEventListener("click", openFromDom, true);
  element.addEventListener("touchend", openFromDom, { capture: true, passive: false });
  element.addEventListener("keydown", (domEvent) => {
    if (domEvent.key === "Enter" || domEvent.key === " ") openFromDom(domEvent);
  });
  element.setAttribute("tabindex", "0");
  element.setAttribute("role", "button");
  element.setAttribute(
    "aria-label",
    `Heat detected by ${joinPlatformNames(area.platforms)}. ${area.detection_count} reading${area.detection_count === 1 ? "" : "s"}.`
  );
}

function renderAreas(hotspotAreas) {
  const areas = visibleAreas(hotspotAreas);
  areas.forEach((area) => {
    const selected = state.selectedArea && state.selectedArea.cell_id === area.cell_id;
    const marker = L.marker([area.center_lat, area.center_lon], {
      icon: heatIcon(area, selected),
      keyboard: true,
      title: `Heat detected by ${area.satellite_count} satellite${area.satellite_count === 1 ? "" : "s"}`,
      alt: `Heat detected by ${joinPlatformNames(area.platforms)}`,
      riseOnHover: true,
      velaAreaId: area.cell_id,
    });
    marker.on("click", (event) => {
      activateArea(areaForMarker(event.target, area), event);
    });
    marker.on("keydown", (event) => {
      if (event.originalEvent.key === "Enter" || event.originalEvent.key === " ") {
        activateArea(areaForMarker(event.target, area), event);
      }
    });
    marker.addTo(map);
    bindHeatMarkerInteractions(marker, area);
    state.areaLayers.push(marker);
    state.markerByCell.set(area.cell_id, marker);
  });
}

function detectionKey(spot) {
  const time = spot.acq_time_raw || spot.acq_time || "";
  return [spot.lat, spot.lon, spot.acq_date, time, spot.platform].join("|");
}

function locationKey(spot) {
  return `${Number(spot.lat).toFixed(4)}|${Number(spot.lon).toFixed(4)}`;
}

function renderIndividuals(payload) {
  state.individualMarkers.forEach((marker) => map.removeLayer(marker));
  state.individualMarkers = [];
  if (!state.showIndividuals || !payload) return;
  const visible = visibleAreas(payload.hotspot_areas);
  const allowed = new Set(
    visible.flatMap((area) => (area.members || []).map((spot) => detectionKey(spot)))
  );
  // Prefer polygon-retained readings from results; fall back to area members.
  let hotspots = (payload.results || []).flatMap((result) => result.hotspots || []);
  if (!hotspots.length) {
    hotspots = visible.flatMap((area) => area.members || []);
  }
  const retained = hotspots.filter((spot) => !allowed.size || allowed.has(detectionKey(spot)));
  const groups = new Map();
  retained.forEach((spot) => {
    const key = locationKey(spot);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(spot);
  });
  groups.forEach((spots) => {
    const primary = spots[0];
    const marker = L.circleMarker([primary.lat, primary.lon], {
      radius: spots.length > 1 ? 6 : 4,
      color: "#fffdf9",
      weight: 1,
      fillColor: INDIVIDUAL_COLORS[primary.platform] || INDIVIDUAL_COLORS.Unrecognized,
      fillOpacity: 0.95,
    });
    marker.bindTooltip(
      spots.length === 1
        ? `${primary.platform} · ${primary.acq_time || ""} UTC`
        : `${spots.length} readings at this location`,
      { sticky: true }
    );
    marker.on("click", (event) => {
      L.DomEvent.stopPropagation(event);
      guardMapClick();
      if (spots.length === 1) showDetection(spots[0]);
      else showDetectionStack(spots);
    });
    marker.addTo(map);
    state.individualMarkers.push(marker);
  });
}

function formatObservationDay(day) {
  if (!day) return "—";
  const [year, month, dayNumber] = String(day).split("-").map(Number);
  if (!year || !month || !dayNumber) return String(day);
  const date = new Date(Date.UTC(year, month - 1, dayNumber));
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

function joinPlatformNames(names) {
  const list = (names || []).filter(Boolean);
  if (!list.length) return "Satellites";
  if (list.length === 1) return list[0];
  if (list.length === 2) return `${list[0]} and ${list[1]}`;
  return `${list.slice(0, -1).join(", ")}, and ${list[list.length - 1]}`;
}

function chronologicalEvents(area) {
  const events = [];
  (area.by_platform || []).forEach((row) => {
    (row.observation_times_utc || []).forEach((time) => {
      events.push({ platform: row.platform, time });
    });
  });
  return events.sort((left, right) => String(left.time).localeCompare(String(right.time)));
}

function buildReplayPasses(area) {
  const members = area.members || [];
  const groups = new Map();
  members.forEach((spot) => {
    const time = spot.acq_time || spot.acq_time_raw || "";
    const key = `${spot.platform}|${spot.acq_date || area.observation_day}|${time}`;
    if (!groups.has(key)) {
      groups.set(key, {
        platform: spot.platform,
        date: spot.acq_date || area.observation_day,
        time,
        members: [],
      });
    }
    groups.get(key).members.push(spot);
  });
  const passes = [...groups.values()].sort((left, right) => {
    const leftStamp = `${left.date} ${left.time}`;
    const rightStamp = `${right.date} ${right.time}`;
    return leftStamp.localeCompare(rightStamp);
  });
  for (let index = 1; index < passes.length; index += 1) {
    passes[index].gapMinutes = minutesBetweenPasses(passes[index - 1], passes[index]);
  }
  return passes;
}

function minutesBetweenPasses(first, second) {
  if (!first?.date || !first?.time || !second?.date || !second?.time) return null;
  const left = Date.parse(`${first.date}T${normalizeTime(first.time)}:00Z`);
  const right = Date.parse(`${second.date}T${normalizeTime(second.time)}:00Z`);
  if (!Number.isFinite(left) || !Number.isFinite(right)) return null;
  return Math.round((right - left) / 60000);
}

function normalizeTime(value) {
  const text = String(value || "");
  if (/^\d{1,2}:\d{2}$/.test(text)) return text.padStart(5, "0");
  const digits = text.replace(/\D/g, "").padStart(4, "0").slice(-4);
  return `${digits.slice(0, 2)}:${digits.slice(2)}`;
}

function formatGap(minutes) {
  if (minutes == null) return "";
  if (minutes < 60) return `${minutes} minutes later`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  if (rem === 0) return `${hours} hour${hours === 1 ? "" : "s"} later`;
  return `${hours} h ${rem} min later`;
}

function leadSentence(area) {
  const count = Number(area.satellite_count || (area.platforms || []).length || 0);
  if (count === 2) return "Two satellites detected heat here.";
  if (count > 2) return `${count} satellites detected heat here.`;
  if (count === 1) return "One satellite detected heat here.";
  return "Heat was detected in this square.";
}

function latestObservation(area) {
  const passes = buildReplayPasses(area);
  if (!passes.length) return null;
  return passes[passes.length - 1];
}

function platformStatuses(area, payload) {
  const order = ["Aqua", "Terra", "Suomi-NPP", "NOAA-20", "NOAA-21"];
  const results = Object.fromEntries((payload.results || []).map((row) => [row.platform, row]));
  const byPlatform = Object.fromEntries((area.by_platform || []).map((row) => [row.platform, row]));
  return order.map((platform) => {
    const feed = results[platform];
    if (!feed) {
      return { platform, text: "Not included in your search." };
    }
    if (feed.status === "product_unavailable" || feed.status === "request_failed") {
      return { platform, text: "Data unavailable for this date." };
    }
    if (byPlatform[platform]) {
      const times = byPlatform[platform].observation_times_utc || [];
      if (times.length === 1) return { platform, text: `Detected heat at ${times[0]} UTC.` };
      if (times.length) return { platform, text: `Detected heat at ${times.map((time) => `${time} UTC`).join("; ")}.` };
      return { platform, text: "Detected heat." };
    }
    if ((feed.coverage || "unknown") !== "unknown") {
      return { platform, text: "Observed this area. No heat detected during this pass." };
    }
    return { platform, text: "No detection returned. Clear view unknown." };
  });
}

function outlineSquare(area, labelText) {
  clearSelectedSquare();
  const bounds = area.bounds;
  // Orbit teal marks the clicked 5 km grid cell; keep the marker uncovered.
  state.selectedSquare = L.rectangle(
    [[bounds.south, bounds.west], [bounds.north, bounds.east]],
    {
      color: "#0f766e",
      weight: 3,
      fillColor: "#14b8a6",
      fillOpacity: 0.1,
      className: "selected-cell-outline",
    }
  ).addTo(map);
  // Small corner badge instead of a wide tooltip over the heat marker.
  state.selectedLabel = L.marker([bounds.south, bounds.west], {
    icon: L.divIcon({
      className: "",
      html: `<div class="selected-cell-badge">${escapeHtml(labelText || "5 km cell")}</div>`,
      iconSize: [72, 18],
      iconAnchor: [0, -4],
    }),
    interactive: false,
  }).addTo(map);
}

function refreshMarkerSelection() {
  state.markerByCell.forEach((marker, cellId) => {
    const area = (state.lastPayload?.hotspot_areas?.areas || []).find((item) => item.cell_id === cellId);
    if (!area) return;
    const selected = state.selectedArea && state.selectedArea.cell_id === cellId;
    marker.setIcon(heatIcon(area, selected));
    // setIcon replaces the DOM node; re-bind so taps still open THIS area.
    bindHeatMarkerInteractions(marker, area);
  });
}

function readingSummary(area) {
  const members = area.members || [];
  const times = [...new Set(members.map((spot) => spot.acq_time).filter(Boolean))].sort();
  if (members.length <= 1) {
    return members.length === 1
      ? "1 satellite reading in this square."
      : "No satellite readings retained for this square.";
  }
  if (times.length === 1) {
    return `${members.length} satellite readings, all at ${times[0]} UTC.`;
  }
  return `${members.length} satellite readings at different times (${times.map((time) => `${time} UTC`).join(", ")}). The later pass saw heat again.`;
}

function showMemberPoints(area, options = {}) {
  clearMemberPoints();
  const activePass = options.pass || null;
  const members = activePass ? activePass.members : area.members || [];
  if (!members.length) return;
  state.memberPointLayer = L.layerGroup().addTo(map);
  members.forEach((spot) => {
    const marker = L.circleMarker([spot.lat, spot.lon], {
      radius: activePass ? 7 : 5,
      color: "#fffdf9",
      weight: 2,
      fillColor: INDIVIDUAL_COLORS[spot.platform] || INDIVIDUAL_COLORS.Unrecognized,
      fillOpacity: 1,
    });
    marker.bindTooltip(
      `${spot.platform} · ${spot.acq_time} UTC · ${Number(spot.lat).toFixed(4)}, ${Number(spot.lon).toFixed(4)} (satellite-reported pixel center)`,
      { sticky: true }
    );
    marker.on("click", (event) => {
      L.DomEvent.stopPropagation(event);
      guardMapClick();
      showDetection(spot);
    });
    marker.addTo(state.memberPointLayer);
  });
}

function renderReplayTimeline(area) {
  const timeline = document.querySelector("#area-timeline");
  const gapNote = document.querySelector("#replay-gap");
  state.replayPasses = buildReplayPasses(area);
  state.replayIndex = 0;
  stopReplayTimer();
  if (!state.replayPasses.length) {
    timeline.innerHTML = "<p class='quiet'>Observation times unavailable.</p>";
    gapNote.hidden = true;
    return;
  }
  timeline.innerHTML = state.replayPasses
    .map((pass, index) => {
      const gap = index > 0 ? formatGap(pass.gapMinutes) : "";
      return `<button type="button" class="timeline-item" role="option" data-pass="${index}" aria-selected="false">
        <strong>${escapeHtml(pass.platform)}</strong>
        <span>${escapeHtml(pass.time)} UTC · ${pass.members.length} pixel${pass.members.length === 1 ? "" : "s"}</span>
        ${gap ? `<span class="gap-note">${escapeHtml(gap)}. Observations at two times; this does not mean heat burned continuously between them.</span>` : ""}
      </button>`;
    })
    .join("");
  timeline.querySelectorAll("[data-pass]").forEach((button) => {
    button.addEventListener("click", () => selectReplayPass(Number(button.dataset.pass)));
  });
  const multiGap = state.replayPasses.length > 1;
  gapNote.hidden = !multiGap;
  if (multiGap) {
    gapNote.textContent =
      "A time gap means observations were made at more than one time. It does not mean the heat burned continuously between passes.";
  }
  selectReplayPass(0);
}

function selectReplayPass(index) {
  if (!state.replayPasses.length) return;
  state.replayIndex = Math.max(0, Math.min(index, state.replayPasses.length - 1));
  const pass = state.replayPasses[state.replayIndex];
  document.querySelectorAll("#area-timeline .timeline-item").forEach((node, nodeIndex) => {
    const on = nodeIndex === state.replayIndex;
    node.classList.toggle("on", on);
    node.setAttribute("aria-selected", on ? "true" : "false");
  });
  if (state.selectedArea) showMemberPoints(state.selectedArea, { pass });
}

function stepReplay(delta) {
  if (!state.replayPasses.length) return;
  selectReplayPass(state.replayIndex + delta);
}

function stopReplayTimer() {
  if (state.replayTimer) {
    window.clearInterval(state.replayTimer);
    state.replayTimer = null;
  }
  const play = document.querySelector("#replay-play");
  if (play) play.textContent = "Replay";
}

function toggleReplay() {
  if (!state.replayPasses.length) return;
  if (state.replayTimer) {
    stopReplayTimer();
    return;
  }
  const play = document.querySelector("#replay-play");
  if (play) play.textContent = "Pause";
  state.replayTimer = window.setInterval(() => {
    if (state.replayIndex >= state.replayPasses.length - 1) {
      selectReplayPass(0);
      return;
    }
    stepReplay(1);
  }, 1400);
}

function panSelectionClearOfPanel(area) {
  if (!area?.center_lat || area.center_lon == null) return;
  const panel = document.querySelector("#area-panel");
  if (!panel || panel.hidden) return;
  const mobile = window.matchMedia("(max-width: 900px)").matches;
  const sheetHeight = panel.getBoundingClientRect().height || 280;
  const panelWidth = panel.getBoundingClientRect().width || 360;
  const point = map.project([area.center_lat, area.center_lon], map.getZoom());
  // Mobile: lift selection above the bottom sheet. Desktop: keep it left of the side panel.
  const target = mobile
    ? L.point(point.x, point.y + sheetHeight * 0.35)
    : L.point(point.x + panelWidth * 0.45, point.y);
  map.panTo(map.unproject(target, map.getZoom()), { animate: true });
}

function setPanelMode(mode) {
  const members = document.querySelector("#area-members");
  const showDetected = document.querySelector("#show-detected-areas");
  const other = document.querySelector("#other-sats");
  if (mode === "empty") {
    members.hidden = true;
    showDetected.hidden = false;
    other.open = true;
  } else {
    members.hidden = false;
    showDetected.hidden = true;
  }
}

function setPlaceLoading(message = "Looking up place…") {
  const label = document.querySelector("#area-place");
  const meta = document.querySelector("#area-place-meta");
  const coordsRow = document.querySelector("#coords-row");
  const attribution = document.querySelector("#place-attribution");
  label.hidden = false;
  label.textContent = message;
  meta.hidden = true;
  meta.textContent = "";
  coordsRow.hidden = true;
  attribution.hidden = true;
  attribution.textContent = "";
  state.lastPlace = null;
}

function renderPlaceResult(place) {
  const label = document.querySelector("#area-place");
  const meta = document.querySelector("#area-place-meta");
  const coordsRow = document.querySelector("#coords-row");
  const coords = document.querySelector("#area-coords");
  const attribution = document.querySelector("#place-attribution");
  state.lastPlace = place || null;
  if (!place) {
    setPlaceLoading("Place name unavailable.");
    return;
  }
  const text = place.label || place.coordinates_text || "Place name unavailable.";
  label.hidden = false;
  label.textContent = text;
  const relationNotes = {
    inside: "Named place containing this selection",
    near: "Nearest verified named place",
    area_near: "Identified from the square center",
    coordinates: "No reliable place name for this point",
  };
  const note = relationNotes[place.relation] || "";
  meta.hidden = !note;
  meta.textContent = note;
  const showCoords = place.relation === "coordinates" || place.status === "unavailable" || !place.primary;
  coordsRow.hidden = !showCoords;
  if (showCoords) {
    coords.textContent = place.coordinates_text
      || (place.lat != null && place.lon != null ? `${Number(place.lat).toFixed(5)}, ${Number(place.lon).toFixed(5)}` : "");
  }
  const source = place.source || {};
  if (source.attribution) {
    attribution.hidden = false;
    const link = source.url
      ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.attribution)}</a>`
      : escapeHtml(source.attribution);
    attribution.innerHTML = `${link} · ${escapeHtml(source.name || "Nominatim")}`;
  } else {
    attribution.hidden = true;
  }
  updateSelectionBanner();
}

async function copyPlaceCoordinates() {
  const coords = document.querySelector("#area-coords")?.textContent?.trim();
  if (!coords) return;
  const button = document.querySelector("#copy-coords");
  try {
    await navigator.clipboard.writeText(coords);
    if (button) {
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = "Copy"; }, 1200);
    }
  } catch (_error) {
    if (button) button.textContent = "Copy failed";
  }
}

async function loadPlaceForSelection(spec, requestToken) {
  setPlaceLoading();
  try {
    const response = await fetch("/api/place", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    });
    const payload = await response.json();
    if (requestToken !== state.placeRequestId) return null;
    renderPlaceResult(payload);
    return payload;
  } catch (_error) {
    if (requestToken !== state.placeRequestId) return null;
    renderPlaceResult({
      status: "unavailable",
      relation: "coordinates",
      label: spec.lat != null && spec.lon != null
        ? `${Number(spec.lat).toFixed(5)}, ${Number(spec.lon).toFixed(5)}`
        : "Place lookup failed.",
      coordinates_text: spec.lat != null && spec.lon != null
        ? `${Number(spec.lat).toFixed(5)}, ${Number(spec.lon).toFixed(5)}`
        : "",
      lat: spec.lat,
      lon: spec.lon,
      source: {
        name: "OpenStreetMap Nominatim",
        attribution: "© OpenStreetMap contributors",
        url: "https://www.openstreetmap.org/copyright",
      },
    });
    return null;
  }
}

function beginPlaceLookup(spec) {
  const token = ++state.placeRequestId;
  // Fire without blocking heat readings / satellite details.
  loadPlaceForSelection(spec, token);
  return token;
}

async function showArea(area) {
  // Always resolve from the clicked cell ID so search-region totals cannot leak in.
  const matched =
    (state.lastPayload?.hotspot_areas?.areas || []).find((item) => item.cell_id === area.cell_id) ||
    area;
  state.selectedArea = matched;
  const detailId = ++state.detailRequestId;
  stopReplayTimer();
  outlineSquare(matched, "5 km cell");
  refreshMarkerSelection();

  setPanelMode("detected");
  openLandPanel({ tab: "where", focus: false });
  // Defer pan until the panel is laid out so width/height are accurate.
  requestAnimationFrame(() => panSelectionClearOfPanel(matched));
  const members = matched.members || [];
  const names = matched.platforms || [];
  const latest = latestObservation(matched);
  document.querySelector("#area-sentence").textContent = leadSentence(matched);
  beginPlaceLookup({
    mode: members.length ? "members" : "center",
    members: members.map((spot) => ({ lat: spot.lat, lon: spot.lon })),
    lat: matched.center_lat,
    lon: matched.center_lon,
    center_lat: matched.center_lat,
    center_lon: matched.center_lon,
  });
  document.querySelector("#area-when").textContent =
    `${joinPlatformNames(names)} · observation day ${formatObservationDay(matched.observation_day)} (UTC)`;
  document.querySelector("#area-latest").textContent = latest
    ? `Latest observation ${latest.time} UTC on ${formatObservationDay(latest.date)}.`
    : "Latest observation time unavailable.";
  document.querySelector("#area-square-note").textContent = "5 km × 5 km observation area";
  document.querySelector("#area-readings").textContent = readingSummary(matched);

  renderReplayTimeline(matched);

  document.querySelector("#unusual-text").textContent = "Checking comparable fire-calendar history…";
  document.querySelector("#unusual-years").textContent = "";
  document.querySelector("#view-fire-calendar").hidden = true;
  document.querySelector("#area-weather-note").textContent =
    matched.observation_day
      ? `Historical observation on ${formatObservationDay(matched.observation_day)}. Current outlook below is dated separately.`
      : "";
  document.querySelector("#area-weather-headline").textContent = "Loading upcoming fire weather…";
  document.querySelector("#area-weather-driver").textContent = "";
  document.querySelector("#area-weather-scope").textContent = "";

  const statuses = platformStatuses(matched, state.lastPayload);
  const otherSats = document.querySelector("#other-sats");
  const otherSummary = otherSats.querySelector("summary");
  if (otherSummary) otherSummary.textContent = "Satellite details for this square";
  document.querySelector("#other-sats-list").innerHTML = statuses
    .map((row) => `<li><strong>${escapeHtml(row.platform)}</strong><br>${escapeHtml(row.text)}</li>`)
    .join("");
  otherSats.open = false;
  const coverage = document.querySelector("#coverage-note");
  const unknownCoverage = statuses.some(
    (row) => !/Detected heat/i.test(row.text) && /Clear view unknown/i.test(row.text)
  );
  coverage.hidden = !unknownCoverage;
  coverage.textContent = unknownCoverage
    ? "Outside the readings above, the available data still don’t tell us whether other satellites had a clear view of the rest of this square."
    : "";

  document.querySelector("#area-members-body").innerHTML = `
    <p class="quiet">${members.length} individual detection${members.length === 1 ? "" : "s"} in this square (cell ${escapeHtml(matched.cell_id)}).</p>
    <table class="member-table">
      <thead><tr><th>Satellite</th><th>Time</th><th>Confidence</th><th>FRP</th><th>Source</th></tr></thead>
      <tbody>${members.map((spot) => `
        <tr>
          <td>${escapeHtml(spot.platform)}</td>
          <td>${escapeHtml(spot.acq_time)} UTC</td>
          <td>${escapeHtml(spot.confidence || "—")}</td>
          <td>${spot.frp ?? "—"}</td>
          <td>${escapeHtml(spot.source || "—")}</td>
        </tr>`).join("")}</tbody>
    </table>`;
  document.querySelector("#area-members").open = false;
  document.querySelector("#area-members").hidden = members.length === 0;

  const wildfire = document.querySelector("#wildfire-line");
  wildfire.innerHTML = "<strong>Wildfire report</strong> · Looking up…";

  const bounds = matched.bounds || {};
  const contextParams = new URLSearchParams({
    west: bounds.west ?? state.box?.[0],
    south: bounds.south ?? state.box?.[1],
    east: bounds.east ?? state.box?.[2],
    north: bounds.north ?? state.box?.[3],
    date: matched.observation_day || dayInput.value,
    cell_id: matched.cell_id,
  });
  try {
    const [wildfireResponse, contextResponse] = await Promise.all([
      fetch(`/api/wildfire-report?${contextParams}`),
      fetch(`/api/area-context?${contextParams}`),
    ]);
    const wildfirePayload = await wildfireResponse.json();
    const contextPayload = await contextResponse.json();
    if (detailId !== state.detailRequestId) return;
    if (wildfirePayload.status === "matched") {
      wildfire.innerHTML = `<strong>Wildfire report</strong> · ${escapeHtml(wildfirePayload.agency)} · ${escapeHtml(wildfirePayload.incident_name)} · ${escapeHtml(wildfirePayload.incident_date)}${wildfirePayload.url ? ` · <a href="${escapeHtml(wildfirePayload.url)}" target="_blank" rel="noopener">source</a>` : ""}`;
    } else if (wildfirePayload.status === "searched_none") {
      wildfire.innerHTML = `<strong>Wildfire report</strong> · No matching report found in ${escapeHtml(wildfirePayload.source)}.`;
    } else {
      wildfire.innerHTML = "<strong>Wildfire report</strong> · Vela has no wildfire-report data for this location.";
    }
    renderUnusualBlock(contextPayload.unusual || {});
    renderAreaWeather(contextPayload.forecast || {}, matched.observation_day);
  } catch (error) {
    if (detailId !== state.detailRequestId) return;
    wildfire.innerHTML = "<strong>Wildfire report</strong> · Vela has no wildfire-report data for this location.";
    document.querySelector("#unusual-text").textContent =
      "Comparable fire-calendar history could not be loaded for this square.";
    document.querySelector("#area-weather-headline").textContent = "Upcoming fire weather unavailable.";
  }

  updateSelectionBanner();
}

function renderUnusualBlock(unusual) {
  document.querySelector("#unusual-text").textContent =
    unusual.text || "Comparable fire-calendar history is unavailable for this square.";
  const years = unusual.baseline_years || [];
  document.querySelector("#unusual-years").textContent = years.length
    ? `Baseline years with adequate coverage: ${years.join(", ")}.`
    : "";
  const button = document.querySelector("#view-fire-calendar");
  button.hidden = false;
  if (unusual.region_name) {
    button.setAttribute("aria-label", `View fire calendar for ${unusual.region_name}`);
  }
}

function renderAreaWeather(forecast, observationDay) {
  const note = document.querySelector("#area-weather-note");
  const headline = document.querySelector("#area-weather-headline");
  const driver = document.querySelector("#area-weather-driver");
  const scope = document.querySelector("#area-weather-scope");
  if (!forecast || !(forecast.days || []).length) {
    headline.textContent = "Upcoming fire weather unavailable.";
    driver.textContent = "";
    scope.textContent = "";
    return;
  }
  note.textContent = observationDay
    ? `Historical observation on ${formatObservationDay(observationDay)}. The outlook below is current and dated separately.`
    : "Current fire-weather outlook for a point near this square.";
  headline.textContent = forecast.headline || "Fire-danger forecast unavailable for this location.";
  const peak = forecast.peak_day;
  if (peak) {
    const humidity = peak.relative_humidity_min_percent || {};
    const wind = peak.wind_speed_max_m_s || {};
    const rain = peak.forecast_rain_mm || {};
    if (humidity.status !== "missing" && humidity.value != null) {
      driver.textContent = `Supported driver: minimum relative humidity ${Number(humidity.value).toFixed(0)}%.`;
    } else if (wind.status !== "missing" && wind.value != null) {
      driver.textContent = `Supported driver: maximum wind speed ${Number(wind.value).toFixed(1)} m/s.`;
    } else if (rain.status !== "missing" && rain.value != null) {
      driver.textContent = `Supported driver: forecast rainfall ${Number(rain.value).toFixed(1)} mm.`;
    } else {
      driver.textContent = peak.explanation || "";
    }
  } else {
    driver.textContent = forecast.headline_explanation || "";
  }
  const point = forecast.point || {};
  scope.textContent =
    point.latitude != null
      ? `Forecast near the center of this 5 km cell (${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)}). ${forecast.forecast_status?.text || ""}`
      : forecast.coverage?.text || "Forecast near the selected cell.";
}

function closeAreaPanel() {
  document.querySelector("#area-panel").hidden = true;
  state.selectedArea = null;
  stopReplayTimer();
  state.replayPasses = [];
  clearSelectedSquare();
  clearMemberPoints();
  refreshMarkerSelection();
}

async function askAboutPoint(lat, lon) {
  if (!state.box || state.ignoreMapClick) return;
  const localMatch = areaContainingPoint(lat, lon, state.lastPayload?.hotspot_areas?.areas || []);
  if (localMatch) {
    guardMapClick();
    showArea(localMatch);
    return;
  }

  const detailId = ++state.detailRequestId;
  const requestId = state.requestId;
  const date = dayInput.value;
  const panel = document.querySelector("#area-panel");
  panel.hidden = false;
  setPanelMode("empty");
  document.querySelector("#area-sentence").textContent =
    `No heat detection was reported in this square on ${formatObservationDay(date)}.`;
  beginPlaceLookup({ mode: "point", lat, lon });
  document.querySelector("#area-when").textContent = "";
  document.querySelector("#area-readings").textContent = "";
  document.querySelector("#area-square-note").textContent =
    "The available data don’t tell us whether a satellite had a clear view here.";
  document.querySelector("#area-timeline").innerHTML = "";
  document.querySelector("#area-points").innerHTML = "";
  document.querySelector("#area-members-body").innerHTML = "";
  document.querySelector("#coverage-note").hidden = true;
  document.querySelector("#wildfire-line").innerHTML =
    "<strong>Wildfire report</strong> · Vela has no wildfire-report data for this location.";
  const otherSats = document.querySelector("#other-sats");
  const otherSummary = otherSats.querySelector("summary");
  if (otherSummary) otherSummary.textContent = "Satellite details for this square";
  document.querySelector("#other-sats-list").innerHTML = "<li>Checking satellite coverage…</li>";
  clearMemberPoints();
  state.selectedArea = null;
  refreshMarkerSelection();

  try {
    const [west, south, east, north] = state.box;
    const response = await fetch("/api/observation-ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        west, south, east, north,
        date,
        lat, lon,
        platforms: selectedPlatforms(),
      }),
    });
    const payload = await response.json();
    if (requestId !== state.requestId || detailId !== state.detailRequestId) return;
    const match = ((payload.hotspot_areas || {}).areas || []).find((area) => area.cell_id === payload.cell_id);
    if (match) {
      showArea(match);
      return;
    }
    const verified = (payload.platform_statuses || []).filter((row) => row.state === "observed_no_heat");
    if (verified.length) {
      document.querySelector("#area-square-note").textContent = verified
        .map((row) => {
          const times = (row.times_utc || row.observation_times_utc || []).filter(Boolean);
          const when = times.length ? ` at ${times.map((time) => `${time} UTC`).join(", ")}` : "";
          return `${row.platform} had a usable pass${when} and reported no heat detection.`;
        })
        .join(" ");
    } else {
      document.querySelector("#area-square-note").textContent =
        "The available data don’t tell us whether a satellite had a clear view here.";
    }
    document.querySelector("#other-sats-list").innerHTML = (payload.platform_statuses || [])
      .map((row) => `<li><strong>${escapeHtml(row.platform)}</strong><br>${escapeHtml(row.text)}</li>`)
      .join("");
    outlineSquare(
      {
        bounds: {
          west: lon - 0.02,
          east: lon + 0.02,
          south: lat - 0.02,
          north: lat + 0.02,
        },
      },
      "Empty square (approximate)"
    );
  } catch (error) {
    if (detailId !== state.detailRequestId) return;
    document.querySelector("#other-sats-list").innerHTML =
      "<li>Coverage lookup failed. Missing evidence is not treated as zero heat.</li>";
  }
  panel.focus({ preventScroll: true });
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

function showDetection(spot) {
  const panel = document.querySelector("#area-panel");
  panel.hidden = false;
  document.querySelector("#area-sentence").textContent =
    `${spot.platform} recorded an individual detection at ${spot.acq_time} UTC.`;
  beginPlaceLookup({ mode: "point", lat: spot.lat, lon: spot.lon });
  document.querySelector("#area-square-note").textContent = "This is one original reading, not a wildfire count.";
  document.querySelector("#area-when").textContent =
    `${spot.platform} · ${spot.acq_date} ${spot.acq_time} UTC`;
  document.querySelector("#area-latest").textContent = "";
  document.querySelector("#area-readings").textContent = "";
  document.querySelector("#area-timeline").innerHTML = `
    <p class="timeline-item"><strong>${escapeHtml(spot.platform)}</strong><span>${escapeHtml(spot.acq_date)} ${escapeHtml(spot.acq_time)} UTC</span></p>`;
  document.querySelector("#area-members-body").innerHTML = `
    <table class="member-table">
      <tbody>
        <tr><th>Confidence</th><td>${escapeHtml(spot.confidence || "—")}</td></tr>
        <tr><th>FRP</th><td>${spot.frp ?? "—"}</td></tr>
        <tr><th>Source</th><td>${escapeHtml(spot.source || "—")}</td></tr>
      </tbody>
    </table>`;
  document.querySelector("#area-members").open = true;
  document.querySelector("#wildfire-line").innerHTML =
    "<strong>Wildfire report</strong> · Individual detections are not wildfire confirmations.";
}

function showDetectionStack(spots) {
  const panel = document.querySelector("#area-panel");
  panel.hidden = false;
  const first = spots[0];
  document.querySelector("#area-sentence").textContent =
    `${spots.length} satellite readings overlap at this location.`;
  beginPlaceLookup({ mode: "point", lat: first.lat, lon: first.lon });
  document.querySelector("#area-square-note").textContent =
    "Choose a reading below. Each row is one original satellite detection.";
  document.querySelector("#area-when").textContent =
    `${Number(first.lat).toFixed(4)}, ${Number(first.lon).toFixed(4)}`;
  document.querySelector("#area-latest").textContent = "";
  document.querySelector("#area-readings").textContent = "";
  document.querySelector("#area-timeline").innerHTML = spots.map((spot, index) => `
    <button type="button" class="timeline-item" data-stack-index="${index}">
      <strong>${escapeHtml(spot.platform)}</strong>
      <span>${escapeHtml(spot.acq_date || "")} ${escapeHtml(spot.acq_time || "")} UTC</span>
    </button>`).join("");
  document.querySelectorAll("#area-timeline [data-stack-index]").forEach((button) => {
    button.addEventListener("click", () => showDetection(spots[Number(button.dataset.stackIndex)]));
  });
  document.querySelector("#area-members-body").innerHTML = "";
  document.querySelector("#area-members").open = false;
  document.querySelector("#wildfire-line").innerHTML =
    "<strong>Wildfire report</strong> · Individual detections are not wildfire confirmations.";
}

function renderResearch(payload) {
  const summary = document.querySelector("#research-summary");
  const host = document.querySelector("#research-feeds");
  const see = document.querySelector("#research-q-see");
  const combine = document.querySelector("#research-q-combine");
  const weekly = document.querySelector("#research-q-weekly");
  const test = document.querySelector("#research-q-test");
  const validation = document.querySelector("#research-validation");
  if (!payload) {
    summary.textContent = "Check your land or select a hotspot to load the records behind this view.";
    if (host) host.innerHTML = "";
    return;
  }
  const areas = payload.hotspot_areas || {};
  const detectionCount = Number(areas.detection_count || 0);
  const areaCount = Number(areas.area_count || 0);
  summary.textContent =
    `${detectionCount} satellite heat reading${detectionCount === 1 ? "" : "s"} across ${areaCount} observation area${areaCount === 1 ? "" : "s"} for this selection. `
    + "A heat reading, a weekly model estimate, forecast fire danger, and an official wildfire report each answer a different question.";
  if (see) {
    see.textContent = detectionCount
      ? `For this land, satellites returned ${detectionCount} heat reading${detectionCount === 1 ? "" : "s"}. Those are sensor detections during a pass, not a count of wildfires.`
      : "For this land, no satellite heat readings were retained inside the boundary for the selected day.";
  }
  if (combine) {
    combine.textContent = areaCount
      ? `Vela grouped those readings into ${areaCount} five-kilometre observation area${areaCount === 1 ? "" : "s"} so you can see which spacecraft contributed.`
      : "When readings exist, Vela groups them into 5 km observation areas without mixing forecast danger or agency reports into the count.";
  }
  if (weekly) {
    weekly.textContent =
      "Weekly trends estimate how often grid squares showed burning activity on days with usable observations or model estimates. Forecast fire danger and official wildfire reports stay separate.";
  }
  if (test) {
    test.textContent =
      "Development validation compares estimates with held-out satellite observations in training regions. Independent final testing is shown below when the model report records it.";
  }
  if (validation) {
    validation.textContent = document.querySelector("#research-performance")?.textContent
      || "Validation status loads with the model report.";
  }
  if (!host) return;
  host.innerHTML = "";
  (payload.results || []).forEach((result) => {
    const article = document.createElement("article");
    article.className = "badge";
    const spots = (result.hotspots || []).slice(0, 8);
    article.innerHTML = `<strong>${escapeHtml(result.platform || "Feed")} · ${escapeHtml(result.product || "—")}</strong>
      <small>${result.count || 0} detections · coverage ${escapeHtml(result.coverage || "unknown")}</small>
      <table class="member-table"><thead><tr><th>Time</th><th>Confidence</th><th>FRP</th></tr></thead>
      <tbody>${spots.map((spot) => `<tr><td>${escapeHtml(spot.acq_time)} UTC</td><td>${escapeHtml(spot.confidence || "—")}</td><td>${spot.frp ?? "—"}</td></tr>`).join("") || "<tr><td colspan='3'>No detections</td></tr>"}</tbody></table>`;
    host.append(article);
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

function formatWeekRange(weekStart, weekEnd) {
  const start = new Date(`${weekStart}T00:00:00Z`);
  const end = new Date(`${weekEnd}T00:00:00Z`);
  const startDay = start.getUTCDate();
  const endDay = end.getUTCDate();
  const startMonth = new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(start);
  const endMonth = new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(end);
  if (startMonth === endMonth) return `${startDay}–${endDay} ${startMonth}`;
  return `${startDay} ${startMonth} – ${endDay} ${endMonth}`;
}

function monthLabel(weekStart) {
  const date = new Date(`${weekStart}T00:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" }).format(date);
}

function weeklyFindingText(published, year) {
  if (!published.length) return "";
  if (published.length === 1) {
    const only = published[0];
    return `We have an estimate for one week in ${year}: ${formatWeekRange(only.week_start, only.week_end)}.`;
  }
  const ranked = [...published].sort((left, right) => Number(right.activity_rate) - Number(left.activity_rate));
  const top = ranked[0];
  const ties = ranked.filter((week) => Number(week.activity_rate) === Number(top.activity_rate));
  if (ties.length > 1) {
    const ranges = ties.map((week) => formatWeekRange(week.week_start, week.week_end)).join("; ");
    return `Among the weeks with usable estimates in ${year}, ${ranges} tied for the highest estimated activity.`;
  }
  return `Among the weeks with usable estimates in ${year}, ${formatWeekRange(top.week_start, top.week_end)} had the highest estimated activity.`;
}

function emptyCalendarReason(payload, weeks) {
  if (!payload || payload.status === "not_processed") {
    return "Weekly history has not been processed for this area.";
  }
  const statuses = (weeks || []).map((week) => week.coverage_status);
  if (statuses.length && statuses.every((status) => status === "not_processed")) {
    return "Weekly history has not been processed for this area.";
  }
  if ((weeks || []).some((week) => week.coverage_status === "insufficient")) {
    return "There was not enough usable coverage to publish weekly estimates for this year.";
  }
  return "No published weekly estimates are available for this land and year.";
}

async function loadAvailableCalendarYears() {
  if (!state.box) {
    state.calendarYears = [];
    return [];
  }
  const [west, south, east, north] = state.box;
  try {
    const response = await fetch(`/api/calendar/years?west=${west}&south=${south}&east=${east}&north=${north}`);
    const payload = await response.json();
    state.calendarYears = payload.years || [];
    return state.calendarYears;
  } catch (_error) {
    state.calendarYears = [];
    return [];
  }
}

function renderEmptyCalendar(year, reason, availableYears) {
  const empty = document.querySelector("#weeks-empty");
  const exportLink = document.querySelector("#export");
  const finding = document.querySelector("#weekly-finding");
  finding.hidden = true;
  finding.textContent = "";
  empty.hidden = false;
  document.querySelector("#weeks-empty-title").textContent = `No weekly estimates for this land in ${year}.`;
  document.querySelector("#weeks-empty-body").textContent =
    "Vela can show individual satellite heat readings for this selection. A weekly trend needs enough observations that can be compared across days.";
  document.querySelector("#weeks-empty-reason").textContent = reason || "";
  const actions = document.querySelector("#weeks-empty-actions");
  actions.innerHTML = "";
  const readings = document.createElement("button");
  readings.type = "button";
  readings.className = "filter-button";
  readings.textContent = "View satellite readings";
  readings.addEventListener("click", () => switchPanelTab("where"));
  actions.append(readings);
  const otherYears = (availableYears || []).filter((row) => Number(row.year) !== Number(year));
  if (otherYears.length) {
    const choose = document.createElement("button");
    choose.type = "button";
    choose.className = "filter-button";
    choose.textContent = `Choose an available year (${otherYears.map((row) => row.year).join(", ")})`;
    choose.addEventListener("click", () => {
      document.querySelector("#year").value = String(otherYears[0].year);
      loadCalendar();
    });
    actions.append(choose);
  }
  if (exportLink) exportLink.hidden = true;
}

async function loadCalendar() {
  const requestId = ++state.calendarRequestId;
  const host = document.querySelector("#weeks");
  const empty = document.querySelector("#weeks-empty");
  const detail = document.querySelector("#week-detail");
  const finding = document.querySelector("#weekly-finding");
  const exportLink = document.querySelector("#export");
  detail.hidden = true;
  empty.hidden = true;
  host.innerHTML = "";
  finding.hidden = true;
  finding.textContent = "";
  if (!state.box) {
    renderEmptyCalendar(document.querySelector("#year").value, "Draw or select land first.", []);
    document.querySelector("#weeks-empty-title").textContent = "No land selected yet.";
    document.querySelector("#weeks-empty-body").textContent =
      "Confirm a boundary on the map, then open Weekly trends again.";
    return;
  }
  const [west, south, east, north] = state.box;
  const year = document.querySelector("#year").value;
  let payload;
  try {
    const response = await fetch(`/api/calendar?west=${west}&south=${south}&east=${east}&north=${north}&year=${year}`);
    if (!response.ok) throw new Error("calendar failed");
    payload = await response.json();
  } catch (_error) {
    if (requestId !== state.calendarRequestId) return;
    renderEmptyCalendar(year, "The weekly request failed. Check your connection and try again.", state.calendarYears);
    return;
  }
  if (requestId !== state.calendarRequestId) return;
  const region = payload.region || {};
  document.querySelector("#region-label").textContent = region.text || "Selected land";
  state.weeks = payload.weeks || [];
  const published = state.weeks.filter((week) => week.activity_status === "complete" || week.activity_status === "partial");
  const availableYears = await loadAvailableCalendarYears();
  if (requestId !== state.calendarRequestId) return;
  if (payload.status === "not_processed" || !published.length) {
    const reason = emptyCalendarReason(payload, state.weeks);
    state.calendarEmptyReason = reason;
    renderEmptyCalendar(year, reason, availableYears);
    return;
  }
  state.calendarEmptyReason = null;
  empty.hidden = true;
  if (exportLink) exportLink.hidden = false;
  finding.hidden = false;
  finding.textContent = weeklyFindingText(published, year);
  let currentMonth = "";
  state.weeks.forEach((week) => {
    const month = monthLabel(week.week_start);
    if (month !== currentMonth) {
      currentMonth = month;
      const label = document.createElement("div");
      label.className = "week-month";
      label.textContent = month;
      host.append(label);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = `week ${week.coverage_status || ""}`;
    const isPublished = week.activity_status === "complete" || week.activity_status === "partial";
    const rate = isPublished ? week.activity_rate : null;
    if (week.clear_zero || (isPublished && rate === 0)) button.classList.add("zero");
    if (week.activity_status === "partial") button.classList.add("partial");
    if (!isPublished) button.classList.add("unavailable");
    if (isPublished && rate > 0) button.classList.add("active");
    const label = isPublished && rate != null ? `${Math.round(rate * 100)}%` : "—";
    button.innerHTML = `<strong>${escapeHtml(formatWeekRange(week.week_start, week.week_end))}</strong><br>${label}`;
    button.addEventListener("click", () => showWeek(week, button));
    host.append(button);
  });
}

function showWeek(week, button) {
  document.querySelectorAll(".week.on").forEach((node) => node.classList.remove("on"));
  button.classList.add("on");
  const detail = document.querySelector("#week-detail");
  detail.hidden = false;
  const revealed = state.revealed.has(week.week_start);
  const observed = revealed ? state.revealed.get(week.week_start) : week.observed_rate;
  const methods = week.method_counts || {};
  const methodLines = Object.entries(methods)
    .filter(([, count]) => Number(count) > 0)
    .map(([name, count]) => `${name}: ${count}`)
    .join(" · ");
  detail.innerHTML = `
    <h3>${escapeHtml(formatWeekRange(week.week_start, week.week_end))}</h3>
    <p><strong>What did Vela estimate for this week?</strong><br>${escapeHtml(activityText(week))}</p>
    <p><strong>How much usable evidence contributed?</strong><br>${escapeHtml(coverageSentence(week))}</p>
    <p><strong>Which satellites supplied observations or model estimates?</strong><br>${escapeHtml(methodLines || "No satellite contribution counts were published for this week.")}</p>
    <div class="numbers">
      ${numberBlock("Eligible coverage", String(week.eligible_coverage_cell_days ?? 0))}
      ${numberBlock("Activity estimates", String(week.activity_estimate_cell_days ?? 0))}
      ${numberBlock("Observed Aqua MODIS", week.held_out && !revealed ? "Hidden until Reveal" : formatShare(observed))}
    </div>
    <p class="quiet">NOAA-20 and NOAA-21 harmonized estimates: calibration pending.</p>
    <div id="cell-contributions"></div>
    <p id="reveal-result"></p>`;
  if (week.reveal_enabled && !revealed) {
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "reveal";
    reveal.textContent = "Reveal MODIS";
    reveal.addEventListener("click", () => revealWeek(week));
    detail.append(reveal);
  }
  loadCellContributions(week);
}

function loadCellContributions(week) {
  const host = document.querySelector("#cell-contributions");
  if (!host || !state.box) return;
  host.innerHTML = "<p class='quiet'>Loading cell-days.</p>";
  const [west, south, east, north] = state.box;
  const params = new URLSearchParams({ west, south, east, north, week_start: week.week_start });
  fetch(`/api/calendar/cells?${params}`)
    .then((response) => response.json())
    .then((payload) => {
      const contributions = payload.contributions || [];
      host.innerHTML = `<p class="quiet">${contributions.length} cell-days with eligible coverage. Activity: ${escapeHtml(activityText(payload))}.</p>`;
    })
    .catch(() => {
      host.innerHTML = "<p class='quiet'>Cell-day contributions are missing.</p>";
    });
}

function activityText(week) {
  if (week.activity_status === "hidden") return "Hidden until Reveal";
  if (week.activity_status === "unavailable" || week.activity_rate == null) return "unavailable";
  return `${(week.activity_rate * 100).toFixed(1)}% of ${week.activity_denominator ?? week.activity_estimate_cell_days}`;
}

function coverageSentence(week) {
  if (week.coverage_status === "not_processed") return "This week has no stored paired observations.";
  return `${week.eligible_coverage_cell_days ?? 0} cell-days have eligible coverage. A missing rate is not a clear zero.`;
}

function numberBlock(label, value) {
  return `<div><span>${label}</span><strong>${value}</strong></div>`;
}

function formatShare(value) {
  if (value == null) return "Not available";
  return `${(value * 100).toFixed(1)}% of usable cell-days`;
}

async function revealWeek(week) {
  const [west, south, east, north] = state.box;
  const response = await fetch("/api/reveal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ west, south, east, north, week_start: week.week_start }),
  });
  const payload = await response.json();
  const node = document.querySelector("#reveal-result");
  if (!payload.ok) {
    node.textContent = payload.reason || "Reveal is not available.";
    return;
  }
  state.revealed.set(week.week_start, payload.observed_rate);
  node.textContent = `Observed Aqua MODIS: ${formatShare(payload.observed_rate)}.`;
}

async function showTrace() {
  const detail = document.querySelector("#trace-detail");
  detail.hidden = false;
  detail.innerHTML = "<p class='quiet'>Loading a traced grid square…</p>";
  switchPanelTab("research");
  const response = await fetch("/api/trace");
  const payload = await response.json();
  if (!payload.available || !(payload.examples || []).length) {
    detail.innerHTML = "<h3>No traced cell yet</h3><p class='quiet'>Run the one-pass verification after Earthdata login.</p>";
    return;
  }
  state.traces = payload;
  const choices = (payload.examples || []).map((example) => `
    <button type="button" class="ghost trace-choice" data-outcome="${escapeHtml(example.outcome)}">${escapeHtml(example.title)}</button>`).join("");
  detail.innerHTML = `<div class="result-filter">${choices}</div><div id="trace-body"></div>`;
  renderTrace(payload.examples[0].outcome);
}

function renderTrace(outcome) {
  const detail = document.querySelector("#trace-detail");
  const body = document.querySelector("#trace-body") || detail;
  const example = (state.traces?.examples || []).find((item) => item.outcome === outcome) || state.traces?.examples?.[0];
  if (!example) return;
  const regionNote = example.region_id === "zambia"
    ? "Saved Zambia woodland example."
    : example.region_id === "cerrado"
      ? "Brazilian Cerrado development example."
      : `Region ${example.region_id || "unknown"}.`;
  body.innerHTML = `
    <h3>${escapeHtml(example.title)} · cell ${escapeHtml(example.cell_id)}</h3>
    <p class="quiet">${escapeHtml(regionNote)} Local date ${escapeHtml(example.local_date || "—")}.</p>
    <p><strong>What each satellite observed</strong><br>
      Aqua/MODIS: ${escapeHtml(example.modis_time_local || example.modis_time_utc || "no usable observation recorded")}.<br>
      VIIRS: ${escapeHtml(example.viirs_time_local || example.viirs_time_utc || "no usable observation recorded")}.
    </p>
    <p><strong>Which observation or estimate contributed</strong><br>
      Shared visible coverage ${example.shared_coverage_fraction != null ? `${(Number(example.shared_coverage_fraction) * 100).toFixed(0)}%` : "—"}.
      ${escapeHtml(example.zero_check?.text || "Contribution details are listed in the technical records for this cell.")}
    </p>
    <p><strong>How it affected the weekly result</strong><br>
      This cell-day is one of the usable squares that can raise or leave unchanged the weekly activity percentage.
      Development validation compared estimates with held-out observations; independent final testing is recorded separately when completed.
    </p>`;
  traceLayer.clearLayers();
  const bounds = example.bounds;
  if (!bounds) return;
  L.rectangle([[bounds.south, bounds.west], [bounds.north, bounds.east]], {
    color: "#1c1612",
    weight: 2,
    fillOpacity: 0,
  }).addTo(traceLayer);
  map.fitBounds([[bounds.south, bounds.west], [bounds.north, bounds.east]], { maxZoom: 10, padding: [28, 28] });
}

function snapshotLandSelection() {
  return {
    box: state.box ? [...state.box] : null,
    polygon: state.polygon ? state.polygon.map((point) => [...point]) : null,
    placeName: state.placeName,
    landLabel: state.landLabel,
    day: dayInput.value,
    year: document.querySelector("#year").value,
    lastPayload: state.lastPayload,
    lastLandCheck: state.lastLandCheck,
    selectedArea: state.selectedArea,
  };
}

async function loadZambiaWeeklyExample() {
  if (!state.usingSavedExample) state.savedLandSnapshot = snapshotLandSelection();
  state.usingSavedExample = true;
  document.querySelector("#return-selection").hidden = false;
  document.querySelector("#fixture-banner").hidden = false;
  document.querySelector("#fixture-banner").textContent =
    "Saved weekly example · Zambia woodland · 2021. Your previous selection can be restored.";
  dayInput.value = "2021-07-20";
  updateDayWords();
  document.querySelector("#year").value = "2021";
  setPolygon(
    [
      [25.0, -15.5],
      [29.0, -15.5],
      [29.0, -12.5],
      [25.0, -12.5],
      [25.0, -15.5],
    ],
    "Zambia woodland · 2021"
  );
  state.landLabel = "Zambia woodland · 2021";
  state.placeName = "Zambia woodland";
  state.placeRequestId += 1;
  state.lastPlace = {
    label: "Zambia woodland",
    relation: "inside",
    status: "ok",
  };
  updateSelectionBanner();
  openLandPanel({ tab: "weekly" });
  await loadCalendar();
}

async function restoreSavedLandSelection() {
  const saved = state.savedLandSnapshot;
  state.usingSavedExample = false;
  document.querySelector("#return-selection").hidden = true;
  document.querySelector("#fixture-banner").hidden = true;
  if (!saved?.box && !saved?.polygon) {
    clearLand();
    return;
  }
  if (saved.day) {
    dayInput.value = saved.day;
    updateDayWords();
  }
  if (saved.year) document.querySelector("#year").value = saved.year;
  state.placeName = saved.placeName;
  state.landLabel = saved.landLabel;
  if (saved.polygon?.length) setPolygon(saved.polygon, saved.landLabel || "Restored land");
  else if (saved.box) setPolygonFromBox(saved.box, saved.landLabel || "Restored land");
  state.lastPayload = saved.lastPayload;
  state.lastLandCheck = saved.lastLandCheck;
  state.selectedArea = saved.selectedArea;
  if (state.lastPayload) {
    clearMapLayers();
    renderPublicResult(state.lastPayload);
    renderAreas(state.lastPayload.hotspot_areas);
    renderIndividuals(state.lastPayload);
  }
  openLandPanel({ tab: "where" });
  updateSelectionBanner();
}

