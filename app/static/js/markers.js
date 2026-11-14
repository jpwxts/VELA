// Heat markers, individual readings and the selected-square outline on the globe.

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

document.querySelector("#basemap-satellite")?.addEventListener("change", (event) => {
  state.basemap = event.target.checked ? "satellite" : "atlas";
  globe.setBasemap(state.basemap);
  drawLandCutout(state.lastPayload?.hotspot_areas?.areas || []);
});

document.querySelector("#show-individuals").addEventListener("change", (event) => {
  state.showIndividuals = event.target.checked;
  renderIndividuals(state.lastPayload);
});

document.querySelector("#show-detected-areas")?.addEventListener("click", () => {
  closeAreaPanel();
  if (state.lastPayload?.hotspot_areas?.areas?.length) {
    const first = state.lastPayload.hotspot_areas.areas[0];
    flyToBounds(first.bounds, { minSpan: 3 });
  }
});
