// Shared evidence language for the panel, calendar and charts.
function philippinePass(stamp) {
  if (!stamp || !Number.isFinite(Date.parse(stamp))) return "Pass time unavailable";
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", day: "numeric", month: "short", year: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).format(new Date(stamp)) + " PH";
}

function observationPresentation(heat, options = {}) {
  const readings = heat?.inside || [];
  const count = Number(heat?.inside_count ?? readings.length);
  const squares = Number(heat?.hotspot_areas?.area_count || (options.square && count ? 1 : 0));
  const satellites = heat?.platforms_inside || [...new Set(readings.map(row => row.platform))];
  const stamps = readings.map(row => {
    let time = String(row.acq_time || row.acq_time_raw || "");
    if (/^\d{4}$/.test(time)) time = `${time.slice(0, 2)}:${time.slice(2)}`;
    return `${row.acq_date}T${time}:00Z`;
  }).filter(stamp => Number.isFinite(Date.parse(stamp))).sort();
  const latest = heat?.latest_pass_ph || stamps.at(-1);
  if (!options.saved && options.date > manilaTodayIso()) return {
    title: "Future day · not yet observed", total: "—", countLine: "Future dates have no observed burning activity.",
    latest: "", scope: `${options.date} · Asia/Manila`,
  };
  const positive = count > 0;
  const title = positive
    ? options.saved ? "Heat in saved snapshot" : options.square ? "Heat detected in this square"
      : options.date === manilaTodayIso() ? "Heat detected today" : "Heat detected on the selected day"
    : heat?.status === "loading" ? "Checking satellite heat…"
      : heat?.status === "unavailable" ? "Satellite heat feed unavailable" : "No heat readings returned";
  return {
    title, total: positive ? String(squares) : heat?.coverage === "observed" && heat.status !== "unavailable" ? "0" : "—",
    countLine: positive
      ? `${count} satellite reading${count === 1 ? "" : "s"} · ${satellites.join(", ")}`
      : heat?.status === "unavailable" ? "The feed failed or is unavailable; this is not an observed zero."
        : heat?.status === "loading" ? "Satellite observations load independently of weather and coverage."
          : `No satellite heat readings returned for this search. ${heat?.coverage === "observed" ? "Usable coverage is reported." : "Clear-view coverage is unknown."}`,
    latest: positive ? `Latest observation · ${philippinePass(latest)}` : "",
    scope: options.saved ? "Saved UTC-day snapshot · not live NASA data. Philippine pass dates are shown."
      : `${options.square ? "Selected 5 km square" : "Selected land boundary"} · ${options.date || "date pending"} · Asia/Manila`,
  };
}

function renderObservedAnswer(heat, options = {}) {
  state.currentEvidenceHeat = heat;
  const result = observationPresentation(heat, options);
  for (const [id, value] of Object.entries({
    "observed-headline": result.title, "observed-square-count": result.total,
    "observed-square-label": options.square ? "5 km square with detected heat" : "5 km squares with detected heat",
    "observed-heat-summary": result.countLine, "observed-latest": result.latest,
    "observation-scope": result.scope,
  })) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }
  renderPredictionExplanation(state.lastHotspotForecast);
}

function predictionExplanation(payload, heat, policy) {
  if (!payload?.method) return ["Square estimates are generated independently of heat and weather.", "Experimental national transfer. No validated wildfire probability is provided."];
  const method = payload.method;
  return [
    `Displayed model: ${payload.model_version} · ${payload.model_hash}. Target: ${payload.target}`,
    method.kind === "historical_prior" ? `Historical fallback: ${method.numerator} positive / ${method.denominator} eligible training square-days. Missing: ${method.missing_inputs.join("; ")}. No local detections are imputed.` : `Classifier inputs: ${JSON.stringify(method.features)}`,
    `Historical records available near this square: ${payload.input_provenance?.historical_record_count ?? "unknown"}. Clear-view coverage: ${payload.input_provenance?.clear_view_coverage || "unknown"}.`,
    `Evaluated geography: ${payload.scope?.evaluated}. Serving geography: Philippine land. ${payload.scope?.in_evaluated_geography ? "Inside" : "Outside"} evaluated geography.`,
    method.assumptions, method.f1_limit || "F1 measures classification at the recorded threshold, not probability calibration.",
    payload.limitation,
  ].filter(Boolean);
}

function renderPredictionExplanation(payload) {
  const list = document.getElementById("forecast-why");
  if (!list) return;
  list.replaceChildren(...predictionExplanation(payload, state.currentEvidenceHeat, state.predictionPolicy).map(text => {
    const li = document.createElement("li"); li.textContent = text; return li;
  }));
}

function renderPolygonPrediction(payload = null) {
  state.lastHotspotForecast = payload?.representative_issue || null;
  const value = document.getElementById("hotspot-forecast-value");
  if (!value) return;
  const summary = payload?.summary;
  const failed = payload && !summary?.forecast_squares;
  const retry = document.getElementById("prediction-retry");
  if (retry) retry.hidden = !failed;
  document.getElementById("hotspot-forecast-label").textContent = "Individual 5 km square estimates";
  value.classList.toggle("is-words", !summary?.forecast_squares);
  value.textContent = summary?.forecast_squares ? (Math.abs(summary.min_percent - summary.max_percent) < 0.1 ? `${summary.min_percent.toFixed(1)}%` : `${summary.min_percent.toFixed(1)}–${summary.max_percent.toFixed(1)}%`) : failed ? "Estimate unavailable" : "Computing square estimates…";
  document.getElementById("hotspot-forecast-meta").textContent = summary?.forecast_squares
    ? "Range of individual square estimates · select a marker for its issue and methods."
    : payload?.reason || "Satellite observations load independently.";
  document.getElementById("polygon-prediction-summary").textContent = summary?.forecast_squares
    ? `${summary.forecast_squares} of ${summary.eligible_land_squares} squares shown${summary.partial ? " · partial layer; draw a smaller boundary for all squares" : ""}. Sum of estimates: ${summary.expected_heat_squares.toFixed(1)} expected heat squares in the displayed set; not an any-event probability.` : "";
  const issue = payload?.representative_issue;
  document.getElementById("model-f1").textContent = issue?.evaluation
    ? `Model F1: ${Number(issue.evaluation.test.f1).toFixed(4)} (test n=${issue.evaluation.test.n}); validation ${Number(issue.evaluation.validation.f1).toFixed(4)} (n=${issue.evaluation.validation.n}) · ${issue.model_version} · ${issue.evaluation.run_id}. Select a square for its exact methods.`
    : "Select a square to see the measured F1 for its displayed model.";
  renderPredictionExplanation(issue);
}

function calendarEvidence(record, issue, future = false) {
  const heat = !future && record?.heat_status === "readings" && record.heat_count > 0 ? String(record.heat_area_count ?? record.heat_count)
    : !future && record?.heat_status === "checked_empty" ? record.heat_coverage === "observed" ? "0" : "No returns" : "—";
  const forecast = issue?.issuance_kind === "preserved_archive" && !issue.historical_simulation && issue.probability_percent != null
    ? `${issue.probability_percent}%` : "—";
  const activity = !future && ["complete", "partial"].includes(record?.activity_status) && Number.isFinite(record.activity_rate)
    ? `${(record.activity_rate * 100).toFixed(1)}%` : "—";
  return {heat, forecast, activity};
}

document.querySelector("#prediction-retry")?.addEventListener("click", () => {
  if (state.summarySquare?.cellId) loadHotspotForecast(state.summarySquare.cellId);
  else loadProbabilityOverlay();
});
