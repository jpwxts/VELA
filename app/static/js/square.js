// A clicked square: its summary, replay and details.

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

document.querySelector("#cell-back")?.addEventListener("click", leaveCellDetail);

globe.onClick(async (spot) => {
  if (state.ignoreMapClick) return;
  if (state.drawing) {
    addPolygonVertex(spot);
    return;
  }
  if (!state.box || !state.lastPayload) return;
  await askAboutPoint(spot.lat, spot.lon);
});

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
