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
  showForecastPoint: true,
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
  publicSnapshot: null,
  usingSavedExample: false,
  // Atlas shell
  insets: { top: 64, right: 0, bottom: 0, left: 0 },
  basemap: "atlas",
  historyView: "present",
  calendarMonth: null,
  historyDay: null,
  monthHistory: null,
  historyKey: null,
  historyRequestId: 0,
  historyLoading: false,
  historyError: false,
  checkedDays: new Map(),
  checkingDay: null,
  traceOutline: null,
  // Land summary widget
  cutoutToken: 0,
  // A clicked square shown in the summary card instead of the whole land.
  summarySquare: null,
  activityRequestId: 0,
  outlookRequestId: 0,
  dayOutlook: null,
  dayOutlookKey: null,
};

// Ember is reserved for observed heat. The visitor's land is drawn in ink,
// the selected 5 km square in teal, and single satellite readings as ink dots.
const HEAT_FILL = "#ee6540";
const LAND_STROKE = "#e8ebe1";
const CELL_STROKE = "#58b9ad";
const READING_FILL = "#e8ebe1";
const DOT_EDGE = "#0c1311";

const STATUS_TEXT = {
  ok: "Detections returned",
  no_hotspots: "No hotspots returned",
  product_unavailable: "Unavailable for this date",
  request_failed: "Request failed",
  not_configured: "Map key needed",
  area_too_large: "Area too large",
  none_selected: "Select a platform",
};

// The globe is the only map. app.js never touches Cesium directly; see globe.js.
const globe = VelaGlobe.create("map", { creditContainer: document.querySelector("#globe-credits") });

document.querySelector("#toggle-forecast-point")?.addEventListener("change", (event) => {
  state.showForecastPoint = Boolean(event.target.checked);
  syncForecastMarkerVisibility();
});
document.querySelector("#basemap-satellite")?.addEventListener("change", (event) => {
  state.basemap = event.target.checked ? "satellite" : "atlas";
  globe.setBasemap(state.basemap);
  drawLandCutout(state.lastPayload?.hotspot_areas?.areas || []);
});
window.addEventListener("resize", syncGlobeInsets);

// The legend opens and closes from its button at the foot of the rail.
function setLegend(open) {
  document.querySelector("#legend-panel").hidden = !open;
  document.querySelector("#legend-toggle").setAttribute("aria-expanded", open ? "true" : "false");
}
document.querySelector("#legend-toggle").addEventListener("click", () => {
  setLegend(document.querySelector("#legend-panel").hidden);
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || document.querySelector("#legend-panel").hidden) return;
  if (!event.target.closest("#legend-panel, #legend-toggle")) return;
  setLegend(false);
  document.querySelector("#legend-toggle").focus();
});

const dayInput = document.querySelector("#day");
const today = new Date();
today.setDate(today.getDate() - 7);
dayInput.value = today.toISOString().slice(0, 10);
document.querySelector("#year").value = today.getUTCFullYear();
initializeHistoryPicker();
updateDayWords();

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
document.querySelectorAll("[data-history]").forEach((button) => {
  button.addEventListener("click", () => setHistoryView(button.dataset.history));
});
document.querySelector("#cal-prev")?.addEventListener("click", () => shiftCalendarMonth(-1));
document.querySelector("#cal-next")?.addEventListener("click", () => shiftCalendarMonth(1));
document.querySelector("#history-month")?.addEventListener("change", chooseHistoryMonth);
document.querySelector("#history-year")?.addEventListener("change", chooseHistoryMonth);
document.querySelector("#history-retry")?.addEventListener("click", () => loadMonthlyHistory({ retry: true }));
document.querySelector("#history-chart-range")?.addEventListener("change", renderHistoryChart);
document.querySelector("#history-chart")?.addEventListener("click", chooseHistoryChartItem);
document.querySelector("#history-chart")?.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (!event.target.closest("[data-history-day], [data-history-month]")) return;
  event.preventDefault();
  chooseHistoryChartItem(event);
});
document.querySelector("#cal-grid")?.addEventListener("click", (event) => {
  const day = event.target.closest("[data-day]");
  if (day && !day.disabled) chooseCalendarDay(day.dataset.day);
});
document.querySelector("#day-summary-check")?.addEventListener("click", () => {
  if (state.historyDay) {
    dayInput.value = state.historyDay;
    updateDayWords();
  }
  checkLand();
});
document.querySelector("#future-days")?.addEventListener("click", (event) => {
  const day = event.target.closest("[data-forecast-day]");
  if (day) openForecastDay(day.dataset.forecastDay);
});
document.querySelector("#hours-prev")?.addEventListener("click", () => scrollHours(-1));
document.querySelector("#hours-next")?.addEventListener("click", () => scrollHours(1));
document.querySelector("#hours-strip")?.addEventListener("scroll", updateHoursNav, { passive: true });
// The strip may be filled while its pane is hidden; place it once it has a real width.
if (window.ResizeObserver && document.querySelector("#hours-strip")) {
  let stripWidth = 0;
  new ResizeObserver((entries) => {
    const width = Math.round(entries[0].contentRect.width);
    if (width && !stripWidth) positionHours();
    stripWidth = width;
  }).observe(document.querySelector("#hours-strip"));
}
document.querySelector("#try-example").addEventListener("click", loadCompetitionDemo);
document.querySelector("#try-philippines")?.addEventListener("click", () => loadPhilippinesPublicExample());
document.querySelectorAll("[data-public-region]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!state.publicSnapshot?.day) return;
    loadPhilippinesPublicExample({
      day: state.publicSnapshot.day,
      region: button.dataset.publicRegion,
    });
  });
});
document.querySelector("#draw").addEventListener("click", startPolygonDraw);
document.querySelector("#finish-draw").addEventListener("click", finishPolygonDraw);
document.querySelector("#clear-area").addEventListener("click", clearLand);
document.querySelector("#confirm").addEventListener("click", () => checkLand());
document.querySelector("#day").addEventListener("change", updateDayWords);
document.querySelector("#show-individuals").addEventListener("change", (event) => {
  state.showIndividuals = event.target.checked;
  renderIndividuals(state.lastPayload);
});
document.querySelector("#sheet-close").addEventListener("click", () => {
  const hadLand = Boolean(state.polygon);
  closeAreaPanel();
  if (hadLand) clearLand();
});
document.querySelector("#cell-back")?.addEventListener("click", leaveCellDetail);
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
  // The rail is the tab list for the card: choosing a section also reopens a closed card.
  button.addEventListener("click", () => openLandPanel({ tab: button.dataset.panelTab, focus: false }));
  button.addEventListener("keydown", (event) => {
    const tabs = [...document.querySelectorAll(".panel-tab")];
    const index = tabs.indexOf(button);
    const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
    const back = event.key === "ArrowLeft" || event.key === "ArrowUp";
    let next = null;
    if (forward) next = tabs[(index + 1) % tabs.length];
    else if (back) next = tabs[(index - 1 + tabs.length) % tabs.length];
    else if (event.key === "Home") next = tabs[0];
    else if (event.key === "End") next = tabs[tabs.length - 1];
    if (!next) return;
    event.preventDefault();
    next.focus();
    openLandPanel({ tab: next.dataset.panelTab, focus: false });
  });
});
document.querySelector("#try-zambia")?.addEventListener("click", loadZambiaWeeklyExample);
document.querySelector("#return-selection")?.addEventListener("click", restoreSavedLandSelection);
document.querySelector("#open-weather-tab")?.addEventListener("click", () => switchPanelTab("weather"));
if (document.querySelector("#try-zambia")) document.querySelector("#try-zambia").hidden = false;

globe.onClick(async (spot) => {
  if (state.ignoreMapClick) return;
  if (state.drawing) {
    addPolygonVertex(spot);
    return;
  }
  if (!state.box || !state.lastPayload) return;
  await askAboutPoint(spot.lat, spot.lon);
});

document.querySelector("#show-detected-areas")?.addEventListener("click", () => {
  closeAreaPanel();
  if (state.lastPayload?.hotspot_areas?.areas?.length) {
    const first = state.lastPayload.hotspot_areas.areas[0];
    flyToBounds(first.bounds, { minSpan: 3 });
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
  state.historyView = "past";
  switchPanelTab("weekly");
});

// First paint leaves the globe unobstructed on every screen size.
syncGlobeInsets();
globe.home(false);
setHistoryView(state.historyView);
updateSelectionBanner();

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
  state.savedExample = true;
  renderHotspots(payload);
  updateSelectionBanner();
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
  openLandPanel({ tab: "where", focus: false });
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
  document.querySelector(".card-body")?.scrollTo({ top: 0 });
  if (tabName === "weather") loadWeatherOutlook();
  if (tabName === "weekly") setHistoryView(state.historyView);
  if (tabName === "research") renderResearch(state.lastPayload);
}

function openLandPanel(options = {}) {
  if (!state.box) return;
  const panel = document.querySelector("#area-panel");
  panel.hidden = false;
  syncGlobeInsets();
  updateSelectionBanner();
  switchPanelTab(options.tab || state.panelTab || "where");
  if (options.focus !== false) panel.focus({ preventScroll: true });
}

// Tell the globe which part of the plate the card covers, so flights frame land beside it.
function syncGlobeInsets() {
  const panel = document.querySelector("#area-panel");
  const plate = document.querySelector("#plate");
  const open = Boolean(panel && !panel.hidden);
  plate.classList.toggle("card-open", open);
  const narrow = window.matchMedia("(max-width: 860px)").matches;
  const box = open ? panel.getBoundingClientRect() : null;
  state.insets = {
    top: narrow ? 64 : 44,
    left: 0,
    right: open && !narrow ? box.width + 32 : 0,
    bottom: open && narrow ? box.height : 0,
  };
  globe.setInsets(state.insets);
}

function flyToBounds(bounds, options = {}) {
  if (!bounds) return;
  syncGlobeInsets();
  globe.flyTo(bounds, options);
}

function mapBadge(text, className) {
  const node = document.createElement("div");
  node.className = `map-badge ${className}`;
  node.textContent = text;
  return node;
}

// Short name for the card title, with the wider region as a breadcrumb above it.
function selectionTitleParts() {
  const place = state.lastPlace;
  if (place && (place.primary || place.label)) {
    const pieces = String(place.label || "").split(",").map((part) => part.trim()).filter(Boolean);
    const title = place.primary || pieces[0];
    let trail = [place.country, place.region || place.province].filter(Boolean);
    if (!trail.length) trail = pieces.slice(1).slice(-2).reverse();
    return { title, trail: trail.filter((part) => part !== title) };
  }
  const name = state.placeName || state.landLabel;
  if (name) {
    const pieces = String(name).split(",").map((part) => part.trim()).filter(Boolean);
    return { title: pieces[0], trail: pieces.slice(1).slice(-2).reverse() };
  }
  if (state.selectedArea) return { title: `5 km square ${state.selectedArea.cell_id}`, trail: [] };
  return { title: state.box ? "Selected land" : "Find your land", trail: [] };
}

function updateSelectionBanner() {
  const place = document.querySelector("#selection-place");
  const boundary = document.querySelector("#selection-boundary");
  const crumb = document.querySelector("#selection-eyebrow");
  const { title, trail } = selectionTitleParts();
  place.textContent = title;
  crumb.hidden = !trail.length;
  crumb.textContent = trail.join(" / ");
  if (state.box) {
    const [west, south, east, north] = state.box;
    const corners = state.polygon ? Math.max(0, state.polygon.length - 1) : 4;
    const shape = state.polygon ? `${corners} corners` : "Search boundary";
    const saved = state.savedExample ? "Saved example · " : "";
    boundary.innerHTML =
      `${saved}${escapeHtml(shape)} · ${escapeHtml(formatObservationDay(dayInput.value))}<br>`
      + `<span class="stamp coords">`
      + [`W ${west}`, `S ${south}`, `E ${east}`, `N ${north}`].map((pair) => `<span>${pair}</span>`).join(" ")
      + `</span>`;
  } else {
    boundary.textContent = "No land selected yet.";
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
  state.publicSnapshot = null;
  const regionFilters = document.querySelector("#philippines-region-filters");
  if (regionFilters) regionFilters.hidden = true;
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

function clearWeatherOutlook() {
  renderOutlook(null, weatherSelectors());
  const location = document.querySelector("#weather-location");
  if (location) {
    location.textContent =
      "Check your land to load a seven-day outlook near the center of your plot.";
  }
  const banner = document.querySelector("#weather-fixture-banner");
  if (banner) banner.hidden = true;
  const retry = document.querySelector("#weather-retry");
  if (retry) retry.hidden = true;
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


async function loadPhilippinesPublicExample(options = {}) {
  const day = options.day || "2026-11-07";
  const region = options.region || "philippines";
  const requestId = ++state.landRequestId;
  state.publicSnapshot = { day, region };
  state.savedExample = true;
  openLandPanel({ tab: "where", focus: false });
  const regionFilters = document.querySelector("#philippines-region-filters");
  if (regionFilters) regionFilters.hidden = false;
  document.querySelector("#area-label").textContent =
    region === "mindanao"
      ? "Loading Mindanao filter of the Philippine snapshot…"
      : "Loading Philippine satellite snapshot…";
  try {
    const response = await fetch(
      `/api/public/philippines/${encodeURIComponent(day)}?region=${encodeURIComponent(region)}`
    );
    const payload = await response.json();
    if (requestId !== state.landRequestId) return;
    if (!response.ok) throw new Error(payload.detail || "Snapshot failed to load");
    dayInput.value = payload.observation_date || day;
    updateDayWords();
    const ring = payload.display_ring || payload.polygon?.coordinates?.[0] || [];
    if (ring.length) setPolygon(ring, payload.label || "Philippines snapshot");
    else if (payload.bbox) {
      const box = payload.bbox;
      setPolygonFromBox([box.west, box.south, box.east, box.north], payload.label || "Philippines snapshot");
    }
    state.showIndividuals = true;
    const individuals = document.querySelector("#show-individuals");
    if (individuals) individuals.checked = true;
    renderLandCheck(payload);
    const counts = payload.counts || {};
    document.querySelector("#area-label").textContent =
      `Saved snapshot · ${payload.region_label || payload.label || "Philippines"} · ${formatObservationDay(day)} · `
      + `${counts.detections ?? "—"} detections`
      + (counts.areas != null ? ` · ${counts.areas} areas` : "")
      + " · no FIRMS key required.";
    const banner = document.querySelector("#fixture-banner");
    if (banner) {
      banner.hidden = false;
      banner.textContent = payload.fixture?.label
        || "Philippines · 7 Nov 2026 · NASA FIRMS snapshot (no map key required)";
    }
  } catch (error) {
    if (requestId !== state.landRequestId) return;
    document.querySelector("#area-label").textContent =
      "The Philippine snapshot could not be loaded.";
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

function forecastTimezone(forecast) {
  if (state.lastPlace?.country_code === "ph" || state.lastPlace?.timezone === "Asia/Manila") {
    return "Asia/Manila";
  }
  if (forecast?.point?.timezone === "Asia/Manila") return "Asia/Manila";
  return forecast?.point?.timezone || "UTC";
}

function formatDetectionLocalTime(spot) {
  const date = spot.acq_date;
  const time = spot.acq_time || spot.acq_time_raw;
  if (!date || !time) return "—";
  const stamp = `${date}T${String(time).length === 4 ? `${time.slice(0, 2)}:${time.slice(2)}:00` : time}Z`;
  const parsed = new Date(stamp);
  if (Number.isNaN(parsed.getTime())) return `${time} UTC`;
  const tz = forecastTimezone(state.forecast);
  try {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: tz,
    }).format(parsed) + (tz === "Asia/Manila" ? " PH time" : ` ${tz}`);
  } catch (_error) {
    return `${time} UTC`;
  }
}

function formatShortForecastDay(day, timeZone = "UTC") {
  if (!day) return "—";
  const [year, month, dayNumber] = String(day).split("-").map(Number);
  if (!year || !month || !dayNumber) return String(day);
  const date = new Date(Date.UTC(year, month - 1, dayNumber, 12));
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: timeZone || "UTC",
  }).format(date);
}

function fieldLine(label, field, unit, period) {
  if (!field || field.status === "missing" || field.value == null) {
    return `<li><strong>${escapeHtml(label)}</strong> · missing${period ? ` <span class="quiet">(${escapeHtml(period)})</span>` : ""}</li>`;
  }
  const value = Number(field.value);
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
  const zeroNote = field.status === "quiet" && value === 0 ? " (measured zero)" : "";
  return `<li><strong>${escapeHtml(label)}</strong> · ${text} ${escapeHtml(unit)}${zeroNote}${
    period ? ` <span class="quiet">· ${escapeHtml(period)}</span>` : ""
  }</li>`;
}

function windKmhField(day) {
  if (day?.wind_speed_max_km_h?.value != null) return day.wind_speed_max_km_h;
  const ms = day?.wind_speed_max_m_s;
  if (!ms || ms.value == null || ms.status === "missing") return { status: "missing", value: null };
  return { status: ms.status, value: Number((Number(ms.value) * 3.6).toFixed(1)) };
}

function gustKmhField(day) {
  if (day?.wind_gust_max_km_h?.value != null) return day.wind_gust_max_km_h;
  const ms = day?.wind_gust_max_m_s;
  if (!ms || ms.value == null || ms.status === "missing") return { status: "missing", value: null };
  return { status: ms.status, value: Number((Number(ms.value) * 3.6).toFixed(1)) };
}

function dayCardSummary(day) {
  if (day.danger_level) return day.danger_level;
  const fire = day.fire_danger || {};
  if (fire.status === "unavailable" || fire.status === "missing" || fire.fwi == null) {
    return "FWI unavailable";
  }
  const temp = day.temperature_max_c || {};
  if (temp.status !== "missing" && temp.value != null) {
    return `${Number(temp.value).toFixed(0)}°C`;
  }
  const rain = day.forecast_rain_mm || {};
  if (rain.status !== "missing" && rain.value != null) {
    return `${Number(rain.value).toFixed(1)} mm`;
  }
  return "Weather only";
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
  const placeNode = document.querySelector("#weather-place");
  const dateNote = document.querySelector("#weather-date-note");
  const regional = document.querySelector("#weather-regional-ref");

  state.forecast = forecast || null;
  if (forecast?.fixture || forecast?.saved) state.savedExample = true;
  // History's calendar and Future list read the same forecast days.
  renderObservationCalendar();
  renderFutureDays();
  const point = forecast?.point || {};
  const tz = forecastTimezone(forecast);
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

  if (placeNode) {
    const placeLabel =
      state.lastPlace?.label
      || state.placeName
      || state.landLabel
      || document.querySelector("#selection-place")?.textContent
      || "";
    placeNode.hidden = !placeLabel || placeLabel === "Selected land";
    placeNode.textContent = placeLabel;
  }

  if (fixtureBanner) {
    if (forecast?.fixture?.label || forecast?.saved) {
      fixtureBanner.hidden = false;
      fixtureBanner.textContent = forecast.fixture?.label || "Saved weather fixture";
    } else {
      fixtureBanner.hidden = true;
    }
  }

  if (dateNote) {
    const obs = document.querySelector("#day")?.value || "";
    const first = forecast?.days?.[0]?.valid_date;
    const last = forecast?.days?.[forecast.days.length - 1]?.valid_date;
    if (first && last) {
      dateNote.hidden = false;
      let text = `Forecast dates (local ${tz}): ${formatShortForecastDay(first, tz)} – ${formatShortForecastDay(last, tz)}.`;
      if (obs && first && obs < first) {
        text += ` Historical hotspot date under review: ${formatObservationDay(obs)} (separate from this outlook).`;
      }
      dateNote.textContent = text;
    } else {
      dateNote.hidden = true;
      dateNote.textContent = "";
    }
  }

  if (regional) {
    const ref = forecast?.regional_fwi_reference;
    if (ref?.url) {
      regional.hidden = false;
      regional.innerHTML =
        `Regional reference (not a numeric Vela reading): <a href="${escapeHtml(ref.url)}" target="_blank" rel="noopener">${escapeHtml(ref.name || "ASMC FWI map")}</a>. `
        + `${escapeHtml(ref.note || "Vela does not infer ratings from map colors.")}`;
    } else {
      regional.hidden = true;
      regional.textContent = "";
    }
  }

  if (!forecast || !(forecast.days || []).length) {
    headline.textContent = "Forecast values unavailable";
    explanation.textContent = "No outlook days were returned for this location.";
    coverage.textContent = "";
    status.textContent = "";
    daysHost.innerHTML = "";
    detail.hidden = true;
    renderWhyThisDay(null);
    if (meta) meta.innerHTML = "";
    if (retry) retry.hidden = false;
    return;
  }

  if (retry) retry.hidden = valuesAvailable;
  headline.textContent = forecast.headline || "Weather outlook";
  explanation.textContent = forecast.headline_explanation || "";
  coverage.textContent =
    forecast.coverage?.text || point.label || "Weather near the center of your selection.";
  status.textContent = forecast.forecast_status?.text || "";

  daysHost.innerHTML = "";
  (forecast.days || []).forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day-chip";
    button.dataset.date = day.valid_date;
    button.setAttribute("aria-pressed", "false");
    const summary = valuesAvailable ? dayCardSummary(day) : "No values";
    const peak = day.valid_date === forecast.attention_day ? " · peak" : "";
    button.innerHTML = `<span class="day-date">${escapeHtml(
      formatShortForecastDay(day.valid_date, tz)
    )}</span><span class="day-level">${escapeHtml(summary + peak)}</span>`;
    if (!valuesAvailable) button.disabled = true;
    if (day.valid_date === forecast.attention_day) button.classList.add("peak");
    if (!day.danger_level) button.classList.add("fwi-missing");
    button.addEventListener("click", () => showOutlookDay(day, forecast, selectors));
    daysHost.append(button);
  });

  if (meta) meta.innerHTML = outlookMetaHtml(forecast, point, tz);
  renderWhyThisDay(forecast);

  const selected =
    (forecast.days || []).find((day) => day.valid_date === state.selectedForecastDay) ||
    forecast.peak_day ||
    (forecast.days || []).find((day) => day.valid_date === forecast.attention_day) ||
    forecast.days[0];
  // Always fill the detail card when days exist — a blank card next to the strip is a bug.
  if (selected) showOutlookDay(selected, forecast, selectors);
}

function renderWhyThisDay(forecast) {
  const block = document.querySelector("#why-this-day");
  const lead = document.querySelector("#why-this-day-lead");
  const points = document.querySelector("#why-this-day-points");
  const missing = document.querySelector("#why-this-day-missing");
  if (!block || !lead || !points || !missing) return;
  const why = forecast?.why_this_day;
  if (!why?.lead) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  lead.textContent = why.lead;
  points.innerHTML = (why.differences || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  missing.textContent = why.missing_note || "";
}

function outlookMetaHtml(forecast, point, tz = "UTC") {
  const ref = forecast?.regional_fwi_reference;
  return `
    <p><strong>Location</strong> · ${escapeHtml(point.label || "Weather near the center of your selection.")}${
      point.latitude != null
        ? ` (${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)})`
        : ""
    }</p>
    <p><strong>Sources</strong> · Open-Meteo weather · Copernicus GWIS ECMWF Fire Weather Index${
      ref?.url ? ` · regional map reference: ${escapeHtml(ref.name)}` : ""
    }</p>
    <p><strong>Units</strong> · °C, %, km/h, mm · FWI is a unitless index · ranking is a local historical percentile</p>
    <p><strong>Timezone</strong> · ${escapeHtml(tz)}</p>
    <p><strong>Grid</strong> · about ${escapeHtml(String(forecast.grid_resolution_km || 8))} km GWIS cells</p>
    <p><strong>Timing</strong> · ${escapeHtml(forecast.forecast_status?.text || "Issue time unavailable")}</p>
    <p><strong>Class table</strong> · ${escapeHtml(forecast.danger_class_source || "GWIS Fire Danger Classes")}</p>`;
}

function showOutlookDay(day, forecast, selectors) {
  const detail = document.querySelector(selectors.detail);
  const daysHost = document.querySelector(selectors.days);
  state.selectedForecastDay = day.valid_date;
  detail.hidden = false;
  const tz = forecastTimezone(forecast);
  const fire = day.fire_danger || {};
  const fwiAvailable = fire.status === "measured" && fire.fwi != null;
  const fwiText = fwiAvailable
    ? `${Number(fire.fwi).toFixed(1)} (GWIS class: ${day.danger_level || "unclassified"})`
    : "Fire-danger rating unavailable for this day";
  const rankingText =
    fire.ranking == null
      ? "not supplied for this day"
      : `${Number(fire.ranking).toFixed(1)} on the local historical percentile scale (not a wildfire probability)`;
  const wind = windKmhField(day);
  const gust = gustKmhField(day);
  const direction = day.wind_direction_text || null;
  const recent = forecast?.recent_rain || {};
  const ratingNote = day.danger_level
    ? "The rating describes weather that could affect a vegetation fire if one starts. It is not a wildfire probability."
    : "No fire-danger rating was published for this day.";
  detail.innerHTML = `
    <p class="reading-label">${escapeHtml(formatShortForecastDay(day.valid_date, tz))} · Fire-weather danger</p>
    <p class="reading-value">${escapeHtml(day.danger_level || "Not rated")}</p>
    <dl class="stat-grid">
      <div><dt>Temperature</dt><dd>${statText(day.temperature_max_c, "°C")}</dd></div>
      <div><dt>Humidity</dt><dd>${statText(day.relative_humidity_min_percent, "%")}</dd></div>
      <div><dt>Wind</dt><dd>${statText(wind, "km/h")}${
        direction ? `<small>${escapeHtml(direction)}</small>` : ""
      }</dd></div>
      <div><dt>Rain / 24 h</dt><dd>${statText(day.forecast_rain_mm, "mm", 1)}</dd></div>
    </dl>
    ${day.explanation ? `<p>${escapeHtml(day.explanation)}</p>` : ""}
    <p class="quiet">${escapeHtml(pointLabel(forecast))} ${ratingNote}</p>
    <details class="fold">
    <summary>All measurements</summary>
    <ul class="outlook-measures">
      ${fieldLine("Air temperature", day.temperature_max_c, "°C", day.temperature_period || "daily maximum")}
      ${fieldLine("Relative humidity", day.relative_humidity_min_percent, "%", day.humidity_period || "daily minimum")}
      ${fieldLine("Sustained wind", wind, "km/h", day.wind_period || "daily maximum")}
      <li><strong>Wind direction</strong> · ${escapeHtml(direction || "missing")}</li>
      ${fieldLine("Wind gusts", gust, "km/h", day.gust_period || "daily maximum")}
      ${fieldLine("Forecast rainfall", day.forecast_rain_mm, "mm", day.rain_period || "daily total")}
      <li><strong>Recent rainfall</strong> · ${
        recent.millimetres == null
          ? "missing"
          : `${Number(recent.millimetres).toFixed(1)} mm${recent.status === "quiet" ? " (measured zero)" : ""}`
      }${
        recent.start && recent.end
          ? ` <span class="quiet">· ${escapeHtml(recent.start)} to ${escapeHtml(recent.end)}</span>`
          : ""
      }</li>
      <li><strong>Fire Weather Index</strong> · ${escapeHtml(fwiText)}</li>
      <li><strong>Local historical ranking</strong> · ${escapeHtml(rankingText)}</li>
      <li><strong>Source</strong> · ${escapeHtml(forecast?.weather_source || "Open-Meteo")} · FWI ${escapeHtml(
        (fire.source || forecast?.fwi_source || "GWIS").split(".")[0]
      )}</li>
      <li><strong>Valid date</strong> · ${escapeHtml(day.valid_date)} (${escapeHtml(tz)})</li>
      <li><strong>Update / archive time</strong> · ${escapeHtml(
        fire.issue_time || forecast?.forecast_status?.text || "not supplied"
      )}</li>
    </ul>
    </details>`;
  daysHost.querySelectorAll(".day-chip").forEach((node) => {
    const on = node.dataset.date === day.valid_date;
    node.classList.toggle("on", on);
    node.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

// One reading for the stat grid: a value with its unit, or the word "Missing".
function statText(field, unit, digits = 0) {
  if (!field || field.status === "missing" || field.value == null) return "Missing";
  const value = Number(field.value).toFixed(digits);
  return unit === "%" ? `${value}%` : `${value} ${escapeHtml(unit)}`;
}

function pointLabel(forecast) {
  return forecast?.point?.label || "Weather near the center of your selection.";
}

function syncForecastMarkerVisibility() {
  if (!state.forecastMarker) return;
  state.forecastMarker.setVisible(state.showForecastPoint !== false);
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
    document.querySelector("#weather-headline").textContent = "No land selected yet";
    document.querySelector("#weather-explanation").textContent =
      "Search for a place or draw a boundary on the globe to see its fire-weather outlook.";
    location.textContent = "Check your land to load a seven-day outlook near the center of your plot.";
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
    state.forecast = payload;
    applyWeatherOutlook(payload);
    openLandPanel({ tab: "weather", focus: false });
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
  const points = [...(heat.inside || []), ...(heat.nearby || [])];
  state.memberPointLayer = points.map((spot) => globe.addPoint(spot.lat, spot.lon, {
    radius: spot.relation === "inside" ? 7 : 6,
    fill: spot.relation === "inside" ? HEAT_FILL : "#1f6f8b",
    stroke: "#fffdf8",
    weight: 2,
    tooltip: `${spot.platform} · ${spot.acq_time || ""} UTC · ${spot.relation}${spot.relation === "nearby" ? ` · ${spot.distance_km} km` : ""}`,
  }));
  if (points.length) {
    const lats = points.map((spot) => Number(spot.lat));
    const lons = points.map((spot) => Number(spot.lon));
    flyToBounds({
      west: Math.min(...lons),
      south: Math.min(...lats),
      east: Math.max(...lons),
      north: Math.max(...lats),
    }, { minSpan: 0.22 });
  }
}

function clearMapLayers() {
  state.areaLayers.forEach((layer) => layer.remove());
  state.areaLayers = [];
  state.markerByCell.clear();
  state.individualMarkers.forEach((marker) => marker.remove());
  state.individualMarkers = [];
  clearSelectedSquare();
  clearMemberPoints();
}

function clearMemberPoints() {
  if (state.memberPointLayer) {
    state.memberPointLayer.forEach((point) => point.remove());
    state.memberPointLayer = null;
  }
}

function clearSelectedSquare() {
  if (state.selectedSquare) state.selectedSquare.remove();
  if (state.selectedLabel) state.selectedLabel.remove();
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
  const count = document.querySelector("#result-count");
  if (!payload) {
    count.textContent = "";
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
  // A returned empty result with unknown coverage is "no detections returned", never "no heat".
  count.textContent = publicResult.kind === "unknown_empty"
    ? "No detections returned"
    : `${total} area${total === 1 ? "" : "s"} with heat`;
  if (payload.date) {
    state.checkedDays.set(payload.date, { total, multi: multiCount, kind: publicResult.kind || "" });
    renderObservationCalendar();
    renderDaySummary();
  }

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
    lead.textContent = total === 1
      ? "Satellites detected heat in 1 area, reported by one satellite."
      : `Satellites detected heat in ${total} areas. Each area was reported by one satellite.`;
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

// A heat marker is a real button on top of the globe: an ember dot for one
// satellite, the same dot with an outer ring when two or more saw heat there.
function heatMarkerElement(area) {
  const count = Number(area.satellite_count || 1);
  const readings = Number(area.detection_count || 0);
  const button = document.createElement("button");
  button.type = "button";
  button.className = `heat-marker${count > 1 ? " multi" : ""}`;
  button.innerHTML = '<span class="heat-dot"></span>';
  button.title = `Heat seen by ${count} satellite${count === 1 ? "" : "s"}`;
  button.setAttribute("aria-pressed", "false");
  button.setAttribute(
    "aria-label",
    `Heat detected by ${joinPlatformNames(area.platforms)}. ${readings} reading${readings === 1 ? "" : "s"}. Show details.`
  );
  return button;
}

function activateArea(area) {
  // Two activations of the same cell in quick succession open it once.
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

function renderAreas(hotspotAreas) {
  const areas = visibleAreas(hotspotAreas);
  areas.forEach((area) => {
    const element = heatMarkerElement(area);
    element.addEventListener("click", (event) => {
      event.stopPropagation();
      // Resolve from the latest payload so a stale marker never opens old data.
      const current =
        (state.lastPayload?.hotspot_areas?.areas || []).find((item) => item.cell_id === area.cell_id) || area;
      activateArea(current);
    });
    const marker = globe.addOverlay(area.center_lat, area.center_lon, element);
    state.areaLayers.push(marker);
    state.markerByCell.set(area.cell_id, marker);
  });
  refreshMarkerSelection();
  // The legend stays closed until there is heat on the globe to explain; it opens once.
  if (areas.length && !state.legendShown) {
    state.legendShown = true;
    if (!window.matchMedia("(max-width: 860px)").matches) setLegend(true);
  }
}

function detectionKey(spot) {
  const time = spot.acq_time_raw || spot.acq_time || "";
  return [spot.lat, spot.lon, spot.acq_date, time, spot.platform].join("|");
}

function locationKey(spot) {
  return `${Number(spot.lat).toFixed(4)}|${Number(spot.lon).toFixed(4)}`;
}

function renderIndividuals(payload) {
  state.individualMarkers.forEach((marker) => marker.remove());
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
    const marker = globe.addPoint(primary.lat, primary.lon, {
      radius: spots.length > 1 ? 6 : 4,
      fill: READING_FILL,
      stroke: DOT_EDGE,
      weight: 1,
      tooltip: spots.length === 1
        ? `${primary.platform} · ${primary.acq_time || ""} UTC`
        : `${spots.length} readings at this location`,
      onClick: () => {
        guardMapClick();
        if (spots.length === 1) showDetection(spots[0]);
        else showDetectionStack(spots);
      },
    });
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
  // Teal marks the clicked 5 km grid cell; keep the marker uncovered.
  state.selectedSquare = globe.addArea(
    [
      [bounds.west, bounds.south],
      [bounds.east, bounds.south],
      [bounds.east, bounds.north],
      [bounds.west, bounds.north],
    ],
    { stroke: CELL_STROKE, weight: 3, fill: CELL_STROKE, fillOpacity: 0.1 }
  );
  // Small corner badge instead of a wide tooltip over the heat marker.
  state.selectedLabel = globe.addOverlay(
    bounds.south,
    bounds.west,
    mapBadge(labelText || "Selected square", "selected-cell-badge"),
    "below-right"
  );
}

function refreshMarkerSelection() {
  state.markerByCell.forEach((marker, cellId) => {
    const selected = Boolean(state.selectedArea && state.selectedArea.cell_id === cellId);
    marker.element.classList.toggle("selected", selected);
    marker.element.setAttribute("aria-pressed", selected ? "true" : "false");
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
  state.memberPointLayer = members.map((spot) => globe.addPoint(spot.lat, spot.lon, {
    radius: activePass ? 7 : 5,
    fill: READING_FILL,
    stroke: DOT_EDGE,
    weight: 2,
    tooltip: `${spot.platform} · ${spot.acq_time} UTC · ${Number(spot.lat).toFixed(4)}, ${Number(spot.lon).toFixed(4)} (satellite-reported pixel center)`,
    onClick: () => {
      guardMapClick();
      showDetection(spot);
    },
  }));
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

// Move the globe only when the selected square sits under the card or off the plate.
function panSelectionClearOfPanel(area) {
  if (area?.center_lat == null || area.center_lon == null || !area.bounds) return;
  syncGlobeInsets();
  const plate = document.querySelector("#plate").getBoundingClientRect();
  const spot = globe.screenPosition(area.center_lat, area.center_lon);
  const margin = 32;
  const clear =
    spot
    && spot.x > state.insets.left + margin
    && spot.x < plate.width - state.insets.right - margin
    && spot.y > state.insets.top + margin
    && spot.y < plate.height - state.insets.bottom - margin;
  if (clear) return;
  flyToBounds(area.bounds, { minSpan: 0.45 });
}

// A clicked square gets the same summary card as the land: cutout, burning activity, today's hours.
function revealCellDetail(bounds, marks = [], heat = null) {
  openLandPanel({ tab: "where", focus: false });
  const { west, south, east, north } = bounds;
  state.summarySquare = {
    ring: [[west, south], [east, south], [east, north], [west, north], [west, south]],
    box: [west, south, east, north],
    marks,
  };
  document.querySelector("#cell-detail").hidden = true;
  document.querySelector("#land-secondary-content").hidden = true;
  document.querySelector("#satellite-picker").hidden = true;
  document.querySelector("#land-summary").hidden = false;
  document.querySelector("#cell-back").hidden = false;
  setSquareHeat(heat);
  document.querySelector(".card-body")?.scrollTo({ top: 0 });
  drawLandCutout([]);
  loadWeeklyActivity();
  loadDayOutlook();
}

// "Heat seen" / "No heat reported"; satellites are named only when the visitor chose their own set.
function setSquareHeat(heat) {
  const line = document.querySelector("#square-heat");
  if (!heat) {
    line.hidden = true;
    return;
  }
  const chosen = selectedPlatforms();
  const custom = chosen.length !== DEFAULT_PLATFORMS.length
    || chosen.some((name) => !DEFAULT_PLATFORMS.includes(name));
  const names = [...new Set(heat.platforms || [])];
  const words = { seen: "Heat seen", none: "No heat reported", failed: "Heat check failed" };
  let text = words[heat.state] || "Checking for heat…";
  if (heat.state === "seen" && custom && names.length) text += ` by ${joinPlatformNames(names)}`;
  line.textContent = text;
  line.classList.toggle("seen", heat.state === "seen");
  line.hidden = false;
}

function squareAround(lat, lon) {
  return { west: lon - 0.02, east: lon + 0.02, south: lat - 0.02, north: lat + 0.02 };
}

// The land, or the clicked square when one is open.
function summaryTarget() {
  if (state.summarySquare) return { ...state.summarySquare, noun: "square" };
  return { ring: state.polygon, box: state.box, marks: null, noun: "land" };
}

// Leave a heat dot's details and return to the land summary.
function leaveCellDetail() {
  state.selectedArea = null;
  stopReplayTimer();
  state.replayPasses = [];
  clearSelectedSquare();
  clearMemberPoints();
  refreshMarkerSelection();
  document.querySelector("#cell-detail").hidden = true;
  document.querySelector(".card-body")?.scrollTo({ top: 0 });
  refreshLandSummary();
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
  const weatherPlace = document.querySelector("#weather-place");
  if (weatherPlace && place?.label) {
    weatherPlace.hidden = false;
    weatherPlace.textContent = place.label;
  }
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
  outlineSquare(matched, "Selected square");
  refreshMarkerSelection();

  setPanelMode("detected");
  revealCellDetail(matched.bounds || squareAround(matched.center_lat, matched.center_lon), [
    { lat: matched.center_lat, lon: matched.center_lon, multi: Boolean(matched.multiple_satellites) },
  ], { state: "seen", platforms: matched.platforms || [] });
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
      <thead><tr><th>Satellite</th><th>Local time</th><th>UTC</th><th>Confidence</th><th>FRP</th></tr></thead>
      <tbody>${members.map((spot) => `
        <tr>
          <td>${escapeHtml(spot.platform)}</td>
          <td>${escapeHtml(formatDetectionLocalTime(spot))}</td>
          <td>${escapeHtml(spot.acq_time || "—")} UTC</td>
          <td>${escapeHtml(spot.confidence || "—")}</td>
          <td>${spot.frp ?? "—"}</td>
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
  state.summarySquare = null;
  document.querySelector("#cell-back").hidden = true;
  document.querySelector("#satellite-picker").hidden = false;
  setSquareHeat(null);
  document.querySelector("#area-panel").hidden = true;
  document.querySelector("#cell-detail").hidden = true;
  document.querySelector("#land-summary").hidden = !(state.polygon && state.polygon.length >= 4);
  state.selectedArea = null;
  stopReplayTimer();
  state.replayPasses = [];
  clearSelectedSquare();
  clearMemberPoints();
  refreshMarkerSelection();
  syncGlobeInsets();
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
  revealCellDetail(squareAround(lat, lon), [], { state: "checking" });
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
    setSquareHeat({ state: "none" });
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
      "Selected square"
    );
  } catch (error) {
    if (detailId !== state.detailRequestId) return;
    setSquareHeat({ state: "failed" });
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
  revealCellDetail(squareAround(Number(spot.lat), Number(spot.lon)), [{ lat: Number(spot.lat), lon: Number(spot.lon) }],
    { state: "seen", platforms: [spot.platform] });
  const place = spot.place_name || spot.place_or_coordinates
    || (spot.lat != null && spot.lon != null ? `${Number(spot.lat).toFixed(5)}, ${Number(spot.lon).toFixed(5)}` : "Location unavailable");
  const localStamp = spot.acq_date_ph && spot.acq_time_ph
    ? `${formatObservationDay(spot.acq_date_ph)} · ${spot.acq_time_ph} PH time`
    : `${spot.acq_date || ""} ${spot.acq_time || ""} UTC`;
  document.querySelector("#area-sentence").textContent =
    `${spot.platform} recorded an individual detection at ${spot.acq_time || "—"} UTC.`;
  if (spot.place_name) {
    const label = document.querySelector("#area-place");
    const meta = document.querySelector("#area-place-meta");
    if (label) {
      label.hidden = false;
      label.textContent = spot.place_name;
    }
    if (meta) {
      meta.hidden = false;
      meta.textContent = "Named place saved with this snapshot";
    }
  } else {
    beginPlaceLookup({ mode: "point", lat: spot.lat, lon: spot.lon });
  }
  document.querySelector("#area-square-note").textContent = "This is one original reading, not a wildfire count.";
  document.querySelector("#area-when").textContent = `${spot.platform} · ${localStamp}`;
  document.querySelector("#area-latest").textContent =
    `${spot.acq_date || ""} ${spot.acq_time || ""} UTC`
    + (spot.acq_date_ph ? ` · Philippine calendar ${spot.acq_date_ph}` : "");
  document.querySelector("#area-readings").textContent = place;
  document.querySelector("#area-timeline").innerHTML = `
    <p class="timeline-item"><strong>${escapeHtml(spot.platform)}</strong><span>${escapeHtml(localStamp)}</span></p>`;
  document.querySelector("#area-members-body").innerHTML = `
    <table class="member-table">
      <tbody>
        <tr><th>Place</th><td>${escapeHtml(place)}</td></tr>
        <tr><th>UTC</th><td>${escapeHtml(spot.acq_date || "")} ${escapeHtml(spot.acq_time || "")}</td></tr>
        <tr><th>Confidence</th><td>${escapeHtml(spot.confidence || "—")}</td></tr>
        <tr><th>FRP</th><td>${spot.frp ?? "—"}</td></tr>
        <tr><th>Source</th><td>${escapeHtml(spot.source || "NASA FIRMS")}</td></tr>
      </tbody>
    </table>`;
  document.querySelector("#area-members").open = true;
  document.querySelector("#wildfire-line").innerHTML =
    "<strong>Wildfire report</strong> · Individual detections are not wildfire confirmations.";
}

function showDetectionStack(spots) {
  const first = spots[0];
  revealCellDetail(squareAround(Number(first.lat), Number(first.lon)), [
    { lat: Number(first.lat), lon: Number(first.lon), multi: spots.length > 1 },
  ], { state: "seen", platforms: spots.map((spot) => spot.platform) });
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
    combine.textContent =
      "Fire danger here is a published weather-based index for the forecast day, separate from satellite heat detections. It is not a wildfire probability.";
  }
  const fwiNode = document.querySelector("#research-q-fwi");
  if (fwiNode) {
    const ref = state.forecast?.regional_fwi_reference;
    fwiNode.textContent = ref?.url
      ? `Vela reads the Copernicus GWIS ECMWF Fire Weather Index at the forecast point when available. For this selection, ${ref.name} is linked as a regional reference only; Vela never infers a rating from map colors.`
      : "Vela reads the Copernicus GWIS ECMWF Fire Weather Index at the forecast point when the WMS layer returns a number. It does not invent a wildfire probability from FWI, satellite counts, or the harmonization model.";
  }
  if (weekly) {
    weekly.textContent =
      "An official wildfire or fire report, on-the-ground confirmation, or a responsible agency bulletin confirms a wildfire. Satellite heat and fire-danger ratings alone do not.";
  }
  if (test) {
    test.textContent =
      "Weekly activity estimates measure how often grid squares showed burning activity on days with usable observations or model estimates. Development validation compares those estimates with held-out satellite observations; independent final testing is recorded separately when completed.";
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
  // Reading the weekly tables takes several seconds; say so instead of showing a blank pane.
  host.innerHTML = `<p class="quiet weeks-loading">Loading weekly history for ${escapeHtml(year)}…</p>`;
  let payload;
  try {
    const response = await fetch(`/api/calendar?west=${west}&south=${south}&east=${east}&north=${north}&year=${year}`);
    if (!response.ok) throw new Error("calendar failed");
    payload = await response.json();
  } catch (_error) {
    if (requestId !== state.calendarRequestId) return;
    host.innerHTML = "";
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
  host.innerHTML = "";
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
  const completeness =
    week.activity_status === "complete"
      ? "Complete estimate for this week."
      : week.activity_status === "partial"
        ? "Partial estimate — some days in the week lack usable coverage."
        : "No published weekly estimate for this week.";
  detail.innerHTML = `
    <h4>${escapeHtml(formatWeekRange(week.week_start, week.week_end))}</h4>
    <p class="result-lead">${escapeHtml(completeness)} Measured activity: ${escapeHtml(activityText(week))}.</p>
    <p><strong>What was measured for this area and week?</strong><br>${escapeHtml(activityText(week))}</p>
    <p><strong>How much usable coverage was there?</strong><br>${escapeHtml(coverageSentence(week))}</p>
    <p><strong>Is the estimate complete or partial?</strong><br>${escapeHtml(completeness)}</p>
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
    detail.innerHTML = "<h4>No traced cell yet</h4><p class='quiet'>Run the one-pass verification after Earthdata login.</p>";
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
    <h4>${escapeHtml(example.title)} · cell ${escapeHtml(example.cell_id)}</h4>
    <p class="quiet">${escapeHtml(regionNote)} Local date ${escapeHtml(example.local_date || "—")}.</p>
    <p><strong>What each satellite observed</strong><br>
      Aqua/MODIS: ${escapeHtml(example.modis_time_local || example.modis_time_utc || "no usable observation recorded")}.<br>
      VIIRS: ${escapeHtml(example.viirs_time_local || example.viirs_time_utc || "no usable observation recorded")}.
    </p>
    <p><strong>Which observation or estimate supplied this cell-day</strong><br>
      Shared visible coverage ${example.shared_coverage_fraction != null ? `${(Number(example.shared_coverage_fraction) * 100).toFixed(0)}%` : "—"}.
      ${escapeHtml(example.zero_check?.text || "Contribution details are listed in the technical records for this cell.")}
    </p>
    <p><strong>How it affected the weekly result</strong><br>
      This cell-day is one of the usable squares that can raise or leave unchanged the weekly activity percentage.
      Development validation compared estimates with held-out observations; independent final testing is recorded separately when completed.
    </p>`;
  if (state.traceOutline) {
    state.traceOutline.remove();
    state.traceOutline = null;
  }
  const bounds = example.bounds;
  if (!bounds) return;
  state.traceOutline = globe.addArea(
    [
      [bounds.west, bounds.south],
      [bounds.east, bounds.south],
      [bounds.east, bounds.north],
      [bounds.west, bounds.north],
    ],
    { stroke: LAND_STROKE, weight: 2 }
  );
  flyToBounds(bounds, { minSpan: 0.9 });
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
  state.savedExample = true;
  updateSelectionBanner();
  state.historyView = "past";
  openLandPanel({ tab: "weekly" });
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


// ---------- History: monthly activity, weekly records, forecast days ----------

function setHistoryView(name) {
  state.historyView = name;
  document.querySelectorAll("[data-history]").forEach((button) => {
    const on = button.dataset.history === name;
    button.classList.toggle("on", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
  });
  ["past", "present", "future"].forEach((view) => {
    document.querySelector(`#history-${view}`).hidden = view !== name;
  });
  if (name === "past") loadCalendar();
  if (name === "present") {
    renderObservationCalendar();
    renderDaySummary();
    loadMonthlyHistory();
  }
  if (name === "future") {
    if (state.box && !state.forecast) loadWeatherOutlook();
    renderFutureDays();
  }
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function initializeHistoryPicker() {
  const currentYear = Number(todayIso().slice(0, 4));
  const picker = document.querySelector("#history-year");
  picker.innerHTML = Array.from({ length: currentYear - 1989 }, (_, index) => {
    const year = currentYear - index;
    return `<option value="${year}">${year}</option>`;
  }).join("");
  dayInput.max = todayIso();
  document.querySelector("#year").max = currentYear;
}

function setHistoryMonth(value) {
  const maximum = todayIso().slice(0, 7);
  state.calendarMonth = value < "1990-01" ? "1990-01" : value > maximum ? maximum : value;
  state.historyDay = dayInput.value.startsWith(state.calendarMonth) ? dayInput.value : `${state.calendarMonth}-01`;
  renderObservationCalendar();
  renderDaySummary();
  loadMonthlyHistory();
}

function chooseHistoryMonth() {
  setHistoryMonth(`${document.querySelector("#history-year").value}-${document.querySelector("#history-month").value}`);
}

function shiftCalendarMonth(delta) {
  const [year, month] = (state.calendarMonth || todayIso().slice(0, 7)).split("-").map(Number);
  const moved = new Date(Date.UTC(year, month - 1 + delta, 1));
  setHistoryMonth(moved.toISOString().slice(0, 7));
}

function historyPercent(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "—";
}

function historyStatusWords(status) {
  return ({ complete: "Available estimate", partial: "Partial estimate", hidden: "Estimate withheld for validation",
    insufficient: "Insufficient usable coverage", not_processed: "No stored observations", future: "Not yet observed" })[status] || "No estimate";
}

function currentMonthHistory() {
  const payload = state.monthHistory;
  return payload && `${payload.year}-${String(payload.month).padStart(2, "0")}` === state.calendarMonth ? payload : null;
}

async function loadMonthlyHistory(options = {}) {
  if (!state.polygon || state.polygon.length < 4) {
    renderObservationCalendar();
    renderDaySummary();
    return;
  }
  const month = state.calendarMonth || dayInput.value.slice(0, 7);
  const key = JSON.stringify([state.polygon, month]);
  if (!options.retry && state.historyKey === key && state.monthHistory) {
    renderObservationCalendar();
    renderDaySummary();
    return;
  }
  const requestId = ++state.historyRequestId;
  state.historyLoading = true;
  state.historyError = false;
  state.monthHistory = null;
  document.querySelector("#history-present").setAttribute("aria-busy", "true");
  renderObservationCalendar();
  renderDaySummary();
  try {
    const [year, number] = month.split("-").map(Number);
    const response = await fetch("/api/history/month", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coordinates: state.polygon, year, month: number }),
    });
    if (!response.ok) throw new Error("history failed");
    const payload = await response.json();
    if (requestId !== state.historyRequestId) return;
    state.monthHistory = payload;
    state.historyKey = key;
  } catch (_error) {
    if (requestId !== state.historyRequestId) return;
    state.historyError = true;
    state.historyKey = null;
  }
  state.historyLoading = false;
  document.querySelector("#history-present").setAttribute("aria-busy", "false");
  renderObservationCalendar();
  renderDaySummary();
}

// Stored daily estimates drive both the month calendar and the chart. A gap
// always stays missing; it is never inferred from an empty live FIRMS result.
function renderObservationCalendar() {
  const grid = document.querySelector("#cal-grid");
  const title = document.querySelector("#cal-title");
  if (!grid || !title) return;
  const selected = state.historyDay || dayInput.value;
  if (!state.calendarMonth) state.calendarMonth = (selected || todayIso()).slice(0, 7);
  const [year, month] = state.calendarMonth.split("-").map(Number);
  const first = new Date(Date.UTC(year, month - 1, 1));
  title.textContent = new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(first);
  document.querySelector("#history-month").value = String(month).padStart(2, "0");
  document.querySelector("#history-year").value = String(year);
  const latest = todayIso().slice(0, 7);
  document.querySelector("#cal-prev").disabled = state.calendarMonth <= "1990-01";
  document.querySelector("#cal-next").disabled = state.calendarMonth >= latest;
  document.querySelectorAll("#history-month option").forEach((option) => {
    option.disabled = `${year}-${option.value}` > latest;
  });
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const today = todayIso();
  const payload = currentMonthHistory();
  const daily = new Map((payload?.days || []).map((day) => [day.date, day]));
  const cells = ["S", "M", "T", "W", "T", "F", "S"].map(
    (letter) => `<span class="cal-weekday" aria-hidden="true">${letter}</span>`
  );
  for (let blank = 0; blank < first.getUTCDay(); blank += 1) cells.push("<span></span>");
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const record = daily.get(iso);
    const rate = record?.activity_rate;
    const available = typeof rate === "number" && Number.isFinite(rate);
    const classes = ["cal-day", "activity-day"];
    const notes = [available ? `${historyPercent(rate)} burning activity` : historyStatusWords(record?.activity_status)];
    if (available) classes.push(rate > 0 ? "has-activity" : "measured-zero");
    else classes.push("no-estimate");
    if (record?.activity_status === "partial") {
      classes.push("partial");
      notes.push("partial estimate");
    }
    if (iso === today) {
      classes.push("today");
      notes.push("today");
    }
    if (iso === selected) {
      classes.push("selected");
      notes.push("selected day");
    }
    const disabled = iso > today;
    const label = `${formatObservationDay(iso)}${notes.length ? `, ${notes.join(", ")}` : ""}`;
    cells.push(
      `<button type="button" class="${classes.join(" ")}" data-day="${iso}" aria-label="${escapeHtml(label)}"`
      + ` aria-pressed="${iso === selected}" style="--activity-strength:${available ? 10 + Math.min(1, Math.max(0, rate)) * 28 : 0}%"`
      + `${disabled ? " disabled" : ""}><span>${day}</span><span class="cal-day-rate">${available ? historyPercent(rate) : "—"}</span></button>`
    );
  }
  grid.innerHTML = cells.join("");
  const status = document.querySelector("#history-status");
  const published = (payload?.days || []).filter((day) => day.activity_rate != null).length;
  status.textContent = state.historyLoading ? "Loading burning activity…"
    : state.historyError ? "History could not be loaded. Please try again."
    : !state.box ? "Select land to see its burning history."
    : published ? `${published} of ${daysInMonth} days have usable estimates. Select a day for details.`
    : `No burning-activity estimates for ${title.textContent}.`;
  document.querySelector("#history-retry").hidden = !state.historyError;
  document.querySelector("#history-month-rate").textContent = historyPercent(payload?.summary?.activity_rate);
  document.querySelector("#history-days-count").textContent = state.historyLoading ? "…" : `${published} / ${daysInMonth}`;
  const firstObservation = payload?.first_observation;
  document.querySelector("#history-availability").textContent = firstObservation
    ? `Stored observations for this land: ${formatObservationDay(firstObservation)} – ${formatObservationDay(payload.last_observation)}.`
    : "";
  renderHistoryChart();
}

function chooseCalendarDay(iso) {
  if (iso < "1990-01-01" || iso > todayIso()) return;
  dayInput.value = iso;
  updateDayWords();
}

function chooseHistoryChartItem(event) {
  const day = event.target.closest("[data-history-day]");
  const month = event.target.closest("[data-history-month]");
  if (day) chooseCalendarDay(day.dataset.historyDay);
  else if (month) setHistoryMonth(month.dataset.historyMonth);
}

function renderHistoryChart() {
  const svg = document.querySelector("#history-chart");
  if (!svg) return;
  const payload = currentMonthHistory();
  const annual = document.querySelector("#history-chart-range").value === "year";
  const selectedMonth = state.calendarMonth || todayIso().slice(0, 7);
  const [year, month] = selectedMonth.split("-").map(Number);
  const rows = annual
    ? payload?.months || Array.from({ length: 12 }, (_, index) => ({ month: `${year}-${String(index + 1).padStart(2, "0")}` }))
    : payload?.days || Array.from({ length: new Date(Date.UTC(year, month, 0)).getUTCDate() }, (_, index) => ({ date: `${selectedMonth}-${String(index + 1).padStart(2, "0")}` }));
  const monthName = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, 1)));
  document.querySelector("#history-chart-caption").textContent = annual
    ? `Monthly activity in ${year}. Select a bar to open that month.`
    : `Daily activity in ${monthName}. Select a bar to see that day.`;
  const left = 34;
  const bottom = 154;
  const height = 126;
  const width = 292;
  const band = width / rows.length;
  const highest = Math.max(0, ...rows.map((row) => Number.isFinite(row.activity_rate) ? row.activity_rate : 0));
  const axisMaximum = Math.min(1, Math.max(0.1, Math.ceil(highest * 10) / 10));
  const parts = [];
  for (const fraction of [0, 0.5, 1]) {
    const y = bottom - height * fraction;
    parts.push(`<line class="history-chart-grid" x1="${left}" y1="${y}" x2="326" y2="${y}"/>`
      + `<text class="history-chart-axis" x="28" y="${y + 3}" text-anchor="end">${(fraction * axisMaximum * 100).toFixed(0)}%</text>`);
  }
  rows.forEach((row, index) => {
    const key = annual ? row.month : row.date;
    const future = annual ? key > todayIso().slice(0, 7) : key > todayIso();
    const available = typeof row.activity_rate === "number" && Number.isFinite(row.activity_rate);
    const x = left + index * band;
    const barWidth = Math.max(3, band - (annual ? 7 : 3));
    const barHeight = available ? Math.max(2, Math.min(1, Math.max(0, row.activity_rate) / axisMaximum) * height) : 0;
    const selected = annual ? key === selectedMonth : key === (state.historyDay || dayInput.value);
    const label = annual ? new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" })
      .format(new Date(`${key}-01T00:00:00Z`)) : String(index + 1);
    const description = `${annual ? monthLabel(`${key}-01`) : formatObservationDay(key)}: ${available ? historyPercent(row.activity_rate) : historyStatusWords(row.activity_status)}`;
    const attributes = future ? "" : `role="button" tabindex="0" data-history-${annual ? "month" : "day"}="${key}" aria-label="${escapeHtml(description)}"`;
    parts.push(`<g class="history-chart-bar${selected ? " selected" : ""}${row.activity_status === "partial" ? " partial" : ""}" ${attributes}>
      <title>${escapeHtml(description)}</title>
      <rect class="history-chart-hit" x="${x}" y="20" width="${band}" height="138"/>
      ${available ? `<rect class="history-chart-value${row.activity_rate === 0 ? " zero" : ""}" x="${x + (band - barWidth) / 2}" y="${bottom - barHeight}" width="${barWidth}" height="${barHeight}" rx="1"/>`
        : `<text class="history-chart-gap" x="${x + band / 2}" y="${bottom - 3}" text-anchor="middle">${future ? "" : "·"}</text>`}
      ${annual || index === 0 || (index + 1) % 5 === 0 || index === rows.length - 1 ? `<text class="history-chart-axis" x="${x + band / 2}" y="172" text-anchor="middle">${label}</text>` : ""}
    </g>`);
  });
  if (!rows.some((row) => row.activity_rate != null)) {
    parts.push(`<text class="history-chart-empty" x="184" y="91" text-anchor="middle">${state.historyLoading ? "Loading history…" : state.historyError ? "Could not load history" : "No estimates for this period"}</text>`);
  }
  svg.innerHTML = parts.join("");
  document.querySelector("#history-chart-table").innerHTML = `<table class="member-table"><caption class="visually-hidden">Burning activity chart values</caption>
    <thead><tr><th>${annual ? "Month" : "Day"}</th><th>Activity</th><th>Status</th></tr></thead>
    <tbody>${rows.map((row, index) => `<tr><td>${annual ? escapeHtml(monthLabel(`${row.month}-01`)) : index + 1}</td><td>${historyPercent(row.activity_rate)}</td><td>${escapeHtml(historyStatusWords(row.activity_status))}</td></tr>`).join("")}</tbody></table>`;
}

function openForecastDay(iso) {
  const day = (state.forecast?.days || []).find((item) => item.valid_date === iso);
  switchPanelTab("weather");
  if (day) showOutlookDay(day, state.forecast, weatherSelectors());
}

function renderDaySummary() {
  const dateNode = document.querySelector("#day-summary-date");
  const countNode = document.querySelector("#day-summary-count");
  const noteNode = document.querySelector("#day-summary-note");
  const button = document.querySelector("#day-summary-check");
  if (!dateNode || !countNode || !noteNode || !button) return;
  const iso = state.historyDay || dayInput.value;
  const record = (currentMonthHistory()?.days || []).find((entry) => entry.date === iso);
  dateNode.textContent = iso ? formatObservationDay(iso) : "";
  button.hidden = true;
  if (state.checkingDay && state.checkingDay === iso) {
    countNode.textContent = "Checking…";
    noteNode.textContent = "Loading satellite heat for this day.";
  } else if (state.historyLoading) {
    countNode.textContent = "Loading…";
    noteNode.textContent = "Reading stored burning activity for this month.";
  } else if (state.historyError) {
    countNode.textContent = "History unavailable";
    noteNode.textContent = "The request failed. Use Retry history to try again.";
  } else if (record?.activity_rate != null) {
    countNode.textContent = historyPercent(record.activity_rate);
    noteNode.textContent = `${historyStatusWords(record.activity_status)}. ${record.estimated_cell_days} of ${record.eligible_cell_days} observed grid squares have a usable estimate for this day.`;
  } else if (state.box) {
    countNode.textContent = "No estimate";
    noteNode.textContent = historyStatusWords(record?.activity_status);
  } else {
    countNode.textContent = "No land selected";
    noteNode.textContent = "Search for a place or draw a boundary on the globe first.";
  }
  button.hidden = !state.polygon || iso > todayIso() || Boolean(state.checkingDay);
}

function renderFutureDays() {
  const list = document.querySelector("#future-days");
  const note = document.querySelector("#future-note");
  if (!list || !note) return;
  const forecast = state.forecast;
  const days = forecast?.days || [];
  if (!days.length) {
    list.innerHTML = "";
    note.textContent = state.box
      ? "No forecast days are loaded for this land yet. Open Weather outlook to load them."
      : "Check your land to load the fire-weather outlook for the days ahead.";
    return;
  }
  const tz = forecastTimezone(forecast);
  note.textContent =
    "Fire-weather danger near the center of your selection. It describes weather, not a wildfire probability.";
  list.innerHTML = days.map((day) => `
    <li><button type="button" class="future-day" data-forecast-day="${escapeHtml(day.valid_date)}">
      <span>${escapeHtml(formatShortForecastDay(day.valid_date, tz))}</span>
      <strong>${escapeHtml(day.danger_level || "Not rated")}</strong>
    </button></li>`).join("");
}

// ---------- Land summary: cutout, weekly burning activity, today's hours ----------

function refreshLandSummary() {
  const section = document.querySelector("#land-summary");
  const hasLand = Boolean(state.polygon && state.polygon.length >= 4);
  state.summarySquare = null;
  document.querySelector("#cell-back").hidden = true;
  document.querySelector("#satellite-picker").hidden = false;
  setSquareHeat(null);
  state.cutoutToken += 1;
  state.activityRequestId += 1;
  state.outlookRequestId += 1;
  section.hidden = !hasLand;
  document.querySelector("#land-secondary-content").hidden = hasLand;
  if (!hasLand) return;
  drawLandCutout([]);
  loadWeeklyActivity();
  loadDayOutlook();
}

// Plain outline of the land, drawn at once so the frame is never empty while
// the globe is still flying to it (and whenever the globe cannot be captured).
function drawLandOutline(ring, canvas) {
  const context = canvas.getContext("2d");
  const lats = ring.map((point) => point[1]);
  const lons = ring.map((point) => point[0]);
  const south = Math.min(...lats);
  const north = Math.max(...lats);
  const west = Math.min(...lons);
  const east = Math.max(...lons);
  const squeeze = Math.cos((((south + north) / 2) * Math.PI) / 180) || 1;
  const width = Math.max((east - west) * squeeze, 1e-6);
  const height = Math.max(north - south, 1e-6);
  const margin = 18;
  const scale = Math.min((canvas.width - margin * 2) / width, (canvas.height - margin * 2) / height);
  const left = (canvas.width - width * scale) / 2;
  const top = (canvas.height - height * scale) / 2;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.beginPath();
  ring.forEach(([lon, lat], index) => {
    const x = left + (lon - west) * squeeze * scale;
    const y = top + (north - lat) * scale;
    if (index) context.lineTo(x, y);
    else context.moveTo(x, y);
  });
  context.closePath();
  context.fillStyle = "#233127";
  context.fill();
  context.lineJoin = "round";
  context.lineWidth = 3;
  context.strokeStyle = LAND_STROKE;
  context.stroke();
}

async function drawLandCutout(areas) {
  const canvas = document.querySelector("#land-cutout");
  const target = summaryTarget();
  const ring = target.ring;
  if (!canvas || !ring || ring.length < 4) return;
  const token = ++state.cutoutToken;
  if (target.marks) areas = [];
  if (!areas.length) drawLandOutline(ring, canvas);
  const marks = target.marks || areas.map((area) => ({
    lat: area.center_lat,
    lon: area.center_lon,
    multi: Boolean(area.multiple_satellites),
  }));
  // Capture into a spare canvas so a superseded capture never paints over a newer one.
  const spare = document.createElement("canvas");
  spare.width = canvas.width;
  spare.height = canvas.height;
  const paint = async () => {
    if (token !== state.cutoutToken) return false;
    const captured = await globe.snapshot(ring, spare, marks);
    if (!captured || token !== state.cutoutToken) return false;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(spare, 0, 0);
    return true;
  };
  // Map tiles keep sharpening after the globe arrives, so take the picture again a few seconds later.
  if (await paint()) window.setTimeout(paint, 5000);
}

// The big figure: Vela's weekly burning-activity estimate for the week that
// holds the observation date. It exists only where weekly history has been
// processed; everywhere else the widget says so instead of showing a number.
async function loadWeeklyActivity() {
  const label = document.querySelector("#activity-label");
  const value = document.querySelector("#activity-value");
  const note = document.querySelector("#activity-note");
  const target = summaryTarget();
  if (!label || !target.box) return;
  const date = dayInput.value;
  const year = date.slice(0, 4);
  const requestId = ++state.activityRequestId;
  const words = (text) => {
    value.textContent = text;
    value.classList.add("is-words");
  };
  label.textContent = "Burning activity";
  words("Loading…");
  note.hidden = false;
  note.textContent = `Reading the weekly estimate for ${formatObservationDay(date)}.`;
  const [west, south, east, north] = target.box;
  let payload;
  try {
    const response = await fetch(`/api/calendar?west=${west}&south=${south}&east=${east}&north=${north}&year=${year}`);
    if (!response.ok) throw new Error("calendar failed");
    payload = await response.json();
  } catch (_error) {
    if (requestId !== state.activityRequestId) return;
    words("Unavailable");
    note.textContent = "The weekly history request failed. Check your connection, then change the date or redraw to try again.";
    return;
  }
  if (requestId !== state.activityRequestId) return;
  const weeks = payload.weeks || [];
  const published = (week) =>
    week.activity_rate != null && (week.activity_status === "complete" || week.activity_status === "partial");
  const week = weeks.find((item) => item.week_start <= date && date <= item.week_end);
  if (week && published(week)) {
    label.textContent = `Burning activity${target.noun === "square" ? " in this square" : ""} · ${formatWeekRange(week.week_start, week.week_end)}`;
    value.textContent = `${(week.activity_rate * 100).toFixed(1)}%`;
    value.classList.remove("is-words");
    note.textContent =
      (week.activity_status === "partial" ? "Partial estimate: some days that week lacked usable coverage. " : "")
      + `How often this ${target.noun}’s grid squares showed burning activity that week. It is not a wildfire probability.`;
    return;
  }
  words("No estimate yet");
  note.textContent = "";
  note.hidden = true;
}

// Open-Meteo weather codes (WMO) reduced to seven drawn conditions.
function weatherIcon(code, isDay) {
  const cloud = '<path d="M10.500 22.500h11a4 4 0 0 0 .600-7.960 6 6 0 0 0-11.400-.940 3.600 3.600 0 0 0-.200 8.900Z"/>';
  const high = `<g transform="translate(0 -3)">${cloud}</g>`;
  const sun = '<circle cx="16" cy="16" r="4.600"/><path d="M16 6.500v2.200M16 23.300v2.200M6.500 16h2.200M23.300 16h2.200M9.300 9.300l1.550 1.550M21.150 21.150l1.550 1.550M9.300 22.700l1.550-1.550M21.150 10.850l1.550-1.550"/>';
  const moon = '<path d="M22.500 18.600A8.300 8.300 0 0 1 13.400 9.500a7.300 7.300 0 1 0 9.100 9.100Z"/>';
  const smallSun = '<circle cx="21.500" cy="10.500" r="3"/><path d="M21.500 4.800v1.500M27.200 10.500h-1.500M25.530 6.470l-1.060 1.060M17.470 6.470l1.060 1.060"/>';
  const smallMoon = '<path d="M26 11.300a4.600 4.600 0 0 1-5.300-5.300 4.300 4.300 0 1 0 5.300 5.300Z"/>';
  const wrap = (body) => `<svg viewBox="0 0 32 32" aria-hidden="true">${body}</svg>`;
  if (code == null) return { label: "Conditions missing", svg: wrap('<path d="M11 16h10"/>') };
  if (code === 0 || code === 1) {
    return isDay === false ? { label: "Clear night", svg: wrap(moon) } : { label: "Clear", svg: wrap(sun) };
  }
  if (code === 2) {
    return { label: "Partly cloudy", svg: wrap(`${isDay === false ? smallMoon : smallSun}<g transform="translate(-2 2)">${cloud}</g>`) };
  }
  if (code === 3) return { label: "Cloudy", svg: wrap(cloud) };
  if (code === 45 || code === 48) return { label: "Fog", svg: wrap(`${high}<path d="M9 23.500h14M11.500 27h9"/>`) };
  if (code >= 95) return { label: "Thunderstorm", svg: wrap(`${high}<path d="m16.500 21-2.500 4h3.500l-2 3.500"/>`) };
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) {
    return { label: "Snow", svg: wrap(`${high}<path d="M11.500 24h.01M16 24h.01M20.500 24h.01M13.750 27.500h.01M18.250 27.500h.01" stroke-width="2.200"/>`) };
  }
  if (code >= 51) return { label: "Rain", svg: wrap(`${high}<path d="m12.500 23-1.300 3.500M17 23l-1.300 3.500M21.500 23l-1.300 3.500"/>`) };
  return { label: "Cloudy", svg: wrap(cloud) };
}

async function loadDayOutlook() {
  const target = summaryTarget();
  if (!target.box) return;
  const [west, south, east, north] = target.box;
  const lat = (south + north) / 2;
  const lon = (west + east) / 2;
  const key = `${lat.toFixed(3)},${lon.toFixed(3)}`;
  const requestId = ++state.outlookRequestId;
  if (state.dayOutlook && state.dayOutlookKey === key) {
    renderDayOutlook(state.dayOutlook);
    return;
  }
  document.querySelector("#hours-strip").innerHTML = "";
  document.querySelector("#hours-title").textContent = `Today at this ${target.noun}`;
  document.querySelector("#hours-note").hidden = false;
  document.querySelector("#hours-note").textContent = "Loading today’s temperature and wind…";
  let payload = null;
  try {
    const response = await fetch(`/api/day-outlook?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}`);
    if (response.ok) payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (requestId !== state.outlookRequestId) return;
  if (payload && payload.ok) {
    state.dayOutlook = payload;
    state.dayOutlookKey = key;
  }
  renderDayOutlook(payload);
}

function renderDayOutlook(outlook) {
  const strip = document.querySelector("#hours-strip");
  const title = document.querySelector("#hours-title");
  const note = document.querySelector("#hours-note");
  const noun = summaryTarget().noun;
  if (!outlook || !outlook.ok || !(outlook.slots || []).length) {
    strip.innerHTML = "";
    title.textContent = `Today at this ${noun}`;
    note.hidden = false;
    note.textContent = "Today’s temperature and wind could not be loaded. Vela needs a connection to Open-Meteo for this.";
    updateHoursNav();
    return;
  }
  const step = outlook.step_hours || 3;
  const nowHour = outlook.now ? Number(String(outlook.now).slice(11, 13)) : null;
  title.textContent = `Today at this ${noun} · ${formatShortForecastDay(outlook.date, "UTC")}`;
  strip.innerHTML = outlook.slots.map((slot) => {
    const current = nowHour != null && nowHour >= slot.hour && nowHour < slot.hour + step;
    const icon = weatherIcon(slot.weather_code, slot.is_day);
    const clock = `${String(slot.hour).padStart(2, "0")}:00`;
    const temperature = slot.temperature_c == null ? "—" : `${Math.round(slot.temperature_c)}°`;
    const wind = slot.wind_speed_km_h == null ? "wind missing" : `${Math.round(slot.wind_speed_km_h)} km/h`;
    return `<li class="hour${current ? " now" : ""}">
      <span class="hour-time">${current ? "Now" : clock}</span>
      ${icon.svg}<span class="visually-hidden">${escapeHtml(icon.label)}</span>
      <strong class="hour-temp">${temperature}</strong>
      <span class="hour-wind">${wind}</span>
    </li>`;
  }).join("");
  note.textContent = "";
  note.hidden = true;
  positionHours();
}

// Start the strip at the current hour so the rest of the day reads left to right.
function positionHours() {
  const strip = document.querySelector("#hours-strip");
  if (!strip || !strip.clientWidth) return;
  const current = strip.querySelector(".hour.now");
  strip.scrollLeft = current ? Math.max(0, current.offsetLeft - strip.offsetLeft - 14) : 0;
  updateHoursNav();
}

function scrollHours(direction) {
  const strip = document.querySelector("#hours-strip");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  strip.scrollBy({ left: direction * strip.clientWidth, behavior: calm ? "auto" : "smooth" });
}

function updateHoursNav() {
  const strip = document.querySelector("#hours-strip");
  const previous = document.querySelector("#hours-prev");
  const next = document.querySelector("#hours-next");
  if (!strip || !previous || !next) return;
  previous.disabled = strip.scrollLeft <= 2;
  next.disabled = strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 2;
}
