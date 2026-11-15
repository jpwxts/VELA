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

function _fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function _fmtNum(value, digits = 4) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function _metricLine(label, metrics) {
  if (!metrics) return `${label}: no scores yet.`;
  const cm = metrics.confusion_matrix;
  const cmText = Array.isArray(cm) ? ` · CM [[${cm[0]}],[${cm[1]}]]` : "";
  return (
    `${label}: n ${metrics.n ?? "—"} (+${metrics.positives ?? metrics.positive_event_count ?? "—"})`
    + ` · Acc ${_fmtPct(metrics.accuracy)} · P ${_fmtPct(metrics.precision)} · R ${_fmtPct(metrics.recall)}`
    + ` · F1 ${_fmtPct(metrics.f1)} · Brier ${_fmtNum(metrics.brier_score)}`
    + (metrics.pr_auc != null ? ` · PR-AUC ${_fmtPct(metrics.pr_auc)}` : "")
    + (metrics.baseline_brier_score != null ? ` · seasonal Brier ${_fmtNum(metrics.baseline_brier_score)}` : "")
    + (metrics.brier_skill_vs_baseline != null
      ? ` · skill ${Number(metrics.brier_skill_vs_baseline).toFixed(3)}`
      : "")
    + cmText
  );
}

function _renderModelBoard(classifiers, baselines, validationN) {
  const rows = [...(classifiers || []), ...(baselines || []).map((row) => ({ ...row, kind: "baseline" }))];
  if (!rows.length) return "<p class='quiet'>Six-model board not available yet.</p>";
  const head = `<table class="member-table"><thead><tr>
    <th>Model</th><th>Thr</th><th>Acc</th><th>P</th><th>R</th><th>F1</th><th>Brier</th><th>n (val)</th>
  </tr></thead><tbody>`;
  const body = rows.map((row) => {
    const m = row.metrics || {};
    const n = m.n ?? validationN ?? "—";
    return `<tr>
      <td>${escapeHtml(row.name)}${row.kind === "baseline" ? " (baseline)" : ""}</td>
      <td>${row.threshold ?? "—"}</td>
      <td>${_fmtPct(m.accuracy)}</td>
      <td>${_fmtPct(m.precision)}</td>
      <td>${_fmtPct(m.recall)}</td>
      <td>${_fmtPct(m.f1)}</td>
      <td>${_fmtNum(m.brier_score)}</td>
      <td>${n}</td>
    </tr>`;
  }).join("");
  return `${head}${body}</tbody></table>
    <p class="quiet">Validation board · same features/splits/tuning budget. Winner chosen by lowest Brier, not accuracy≈F1.</p>`;
}

async function loadHotspotAnalytics() {
  const summary = document.querySelector("#hotspot-analytics-summary");
  const board = document.querySelector("#hotspot-model-board");
  const v2 = document.querySelector("#hotspot-analytics-v2");
  const v1 = document.querySelector("#hotspot-analytics-v1");
  const replay = document.querySelector("#hotspot-analytics-replay");
  if (!summary || !v2 || !v1) return;
  try {
    const response = await fetch("/api/hotspot-forecast/metrics");
    const payload = await response.json();
    const analytics = payload?.comparison?.analytics || {};
    const current = analytics.v2_1 || {};
    const archived = analytics.v1_archived_experiment || {};
    const holdout = current.holdout || {};
    const claimable = holdout.claimable_ex_v22_reserve || holdout.metrics;
    const candidate = payload?.comparison;
    const prior = payload?.national_prior;
    summary.textContent =
      current.winner
        ? `Research winner: ${candidate.winner.name} · validation F1 ${Number(candidate.winner.validation_metrics.f1).toFixed(4)} (n=${candidate.row_counts.validation}); full-test F1 ${Number(candidate.holdout.metrics.f1).toFixed(4)} (n=${candidate.row_counts.test}). Run ${candidate.data_version}. National estimates are experimental; the displayed square identifies its actual model.`
        : (payload?.comparison?.reason || "Hotspot-forecast model performance unavailable.");
    if (board) {
      board.innerHTML = _renderModelBoard(
        current.classifiers || payload?.comparison?.classifiers,
        current.baselines || payload?.comparison?.baselines,
        current.row_counts?.validation_n || current.row_counts?.validation,
      );
    }
    const seasonal = claimable?.baseline_brier_score;
    const highAudit = payload?.high_probability_audit || {};
    const highBand = highAudit.high_band || {};
    const highNote = highAudit.serving_policy?.limitation_for_research
      || "Scores ≥90% and months outside the dry-season training distribution are labeled experimental.";
    v2.innerHTML = [
      prior ? `<p><strong>National historical fallback</strong> · ${escapeHtml(prior.model_name)} · ${prior.numerator}/${prior.denominator} = ${(prior.probability*100).toFixed(1)}%. Validation F1 ${prior.splits.validation.f1.toFixed(4)} (n=${prior.splits.validation.n}); test F1 ${prior.splits.test.f1.toFixed(4)} (n=${prior.splits.test.n}) at threshold ${prior.threshold}. Run ${escapeHtml(prior.run_id)}.</p><p class="quiet">Used when seven days of measured coverage or a compatible seasonal input is missing. This fixed training rate cannot distinguish local risk. It is not nationally calibrated; an empty satellite search is never filled with assumed detections. The HGB is used only with complete measured inputs in its evaluated seasonal distribution. Both paths are experimental.</p>` : "",
      `<p><strong>Selected model holdout (claimable)</strong></p>`,
      `<p>${_metricLine("Identical claimable rows", claimable)}</p>`,
      seasonal != null ? `<p class="quiet">Seasonal baseline Brier on identical rows: ${_fmtNum(seasonal)}</p>` : "",
      `<p>${_metricLine("Recent-heat squares", holdout.recent_heat_squares)}</p>`,
      `<p>${_metricLine("No recent heat (cold)", holdout.no_recent_heat_squares)}</p>`,
      `<p class="quiet">Full test including sealed reserve is retained for audit only; do not tune on the v2.2 reserve.</p>`,
      `<p><strong>High percentages (experimental)</strong></p>`,
      `<p class="quiet">Claimable 0.9–1.0 band: n ${highBand.n ?? "—"} · mean predicted ${_fmtNum(highBand.mean_predicted)} · observed ${_fmtNum(highBand.observed_detection_frequency)}. ${escapeHtml(highNote)}</p>`,
      highAudit.label_construction_bias?.note
        ? `<p class="quiet">${escapeHtml(highAudit.label_construction_bias.note)}</p>`
        : "",
      payload?.supported_areas?.regions
        ? `<p class="quiet">Supported-area map: ${(payload.supported_areas.regions || []).map((r) => escapeHtml(r.id || r.label || "")).filter(Boolean).join(" · ") || "Maguindanao compact only"}.</p>`
        : "",
      payload?.mindanao_firms_refresh?.checked_at
        ? `<p class="quiet">Mindanao FIRMS refresh: ${escapeHtml(payload.mindanao_firms_refresh.checked_at)} · `
          + `${payload.mindanao_firms_refresh.detection_count ?? "—"} detections`
          + `${payload.mindanao_firms_refresh.ok === false ? " · error" : ""}.</p>`
        : "",
      payload?.mindanao_island_selection
        ? `<p class="quiet">Island selection: ${escapeHtml(payload.mindanao_island_selection.state || "pending")} — `
          + `${escapeHtml(payload.mindanao_island_selection.reason || "not promoted")}.</p>`
        : "",
    ].join("");
    const v1board = (archived.leaderboard || [])
      .map((row) => `${row.name}: Brier ${Number(row.brier).toFixed(4)}`)
      .join(" · ");
    const cold = archived.holdout_enrichment?.no_recent_heat_squares;
    v1.innerHTML = [
      `<p><strong>Archived experiment — coverage labels revised</strong></p>`,
      `<p class="quiet">${escapeHtml(archived.note || "Six v1 models under empty-FIRMS negatives.")}</p>`,
      v1board ? `<p class="quiet">${escapeHtml(v1board)}</p>` : "",
      cold ? `<p class="quiet">${_metricLine("Archived cold squares", cold)}</p>` : "",
    ].join("");
    const preserved = analytics.preserved_replay_example || {};
    if (replay) {
      replay.innerHTML = preserved.cell_id
        ? `<p><strong>Preserved v1 replay</strong> · cell ${escapeHtml(preserved.cell_id)} · `
          + `issue slot ${escapeHtml(preserved.issue_date_ph)} 00:00 Asia/Manila · `
          + `${preserved.probability_percent}% from v1 model ${escapeHtml(preserved.v1_model_version || "—")}. `
          + `${escapeHtml(preserved.note || "")}</p>`
        : "";
    }
  } catch (_error) {
    summary.textContent = "Hotspot-forecast model performance could not be loaded.";
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    loadHotspotAnalytics();
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
