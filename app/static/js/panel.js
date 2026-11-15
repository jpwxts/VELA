// The rail, the card, the legend and the card's title.

// The legend opens and closes from its button at the foot of the rail.
function setLegend(open) {
  document.querySelector("#legend-panel").hidden = !open;
  document.querySelector("#legend-toggle").setAttribute("aria-expanded", open ? "true" : "false");
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
  syncLandPicture();
  if (tabName !== "forecast") clearProbabilitySurface();
  if (tabName === "forecast") {
    if (state.summarySquare?.cellId) loadHotspotForecast(state.summarySquare.cellId);
    else loadProbabilityOverlay();
  }
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
  if (state.summarySquare?.cellId) return {title: `Square ${state.summarySquare.cellId}`, trail: ["Selected 5 km satellite grid square"]};
  if (!state.summarySquare && state.boundaryPreset) return {
    title: state.boundaryPreset === "mindanao" ? "All Mindanao" : "All Philippines",
    trail: ["Philippines", "Complete island-group boundary"],
  };
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
      `${saved}${state.summarySquare ? "Selected 5 km square" : "Selected land"} · ${escapeHtml(formatObservationDay(dayInput.value))}<br>`
      + `<span class="stamp coords">`
      + [`W ${west}`, `S ${south}`, `E ${east}`, `N ${north}`].map((pair) => `<span>${pair}</span>`).join(" ")
      + `</span>`;
  } else {
    boundary.textContent = "No land selected yet.";
  }
}

function closeAreaPanel() {
  state.detailRequestId += 1;
  clearHotspotSearches();
  state.summarySquare = null;
  document.querySelector("#cell-back").hidden = true;
  document.querySelector("#satellite-picker").hidden = false;
  setSquareHeat(null);
  document.querySelector("#area-panel").hidden = true;
  document.querySelector("#cell-detail").hidden = true;
  document.querySelector("#land-summary").hidden = !(state.polygon && state.polygon.length >= 4);
  syncLandPicture();
  state.selectedArea = null;
  stopReplayTimer();
  state.replayPasses = [];
  clearSelectedSquare();
  clearMemberPoints();
  refreshMarkerSelection();
  syncGlobeInsets();
}

window.addEventListener("resize", syncGlobeInsets);

document.querySelector("#legend-toggle").addEventListener("click", () => {
  setLegend(document.querySelector("#legend-panel").hidden);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || document.querySelector("#legend-panel").hidden) return;
  if (!event.target.closest("#legend-panel, #legend-toggle")) return;
  setLegend(false);
  document.querySelector("#legend-toggle").focus();
});

document.querySelector("#sheet-close").addEventListener("click", () => {
  const hadLand = Boolean(state.polygon);
  closeAreaPanel();
  if (hadLand) clearLand();
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

document.querySelector("#open-weather-tab")?.addEventListener("click", () => switchPanelTab("weather"));
