// Saved examples and fixtures.

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
  const requestId = ++state.landRequestId;
  state.savedExample = true;
  openLandPanel({ tab: "where", focus: false });
  document.querySelector("#area-label").textContent = "Loading Philippine satellite snapshot…";
  try {
    const response = await fetch(
      `/api/public/philippines/${encodeURIComponent(day)}?region=philippines`
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

document.querySelector("#try-example").addEventListener("click", loadCompetitionDemo);
document.querySelector("#try-philippines")?.addEventListener("click", () => loadPhilippinesPublicExample());
document.querySelector("#try-zambia")?.addEventListener("click", loadZambiaWeeklyExample);
document.querySelector("#return-selection")?.addEventListener("click", restoreSavedLandSelection);
if (document.querySelector("#try-zambia")) document.querySelector("#try-zambia").hidden = false;
