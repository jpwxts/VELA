// Research tab and the weekly-estimate trace.

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

document.querySelector("#trace")?.addEventListener("click", showTrace);

document.querySelector("#trace-detail")?.addEventListener("click", (event) => {
  const choice = event.target.closest(".trace-choice");
  if (!choice) return;
  renderTrace(choice.dataset.outcome);
});
