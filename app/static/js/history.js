// History tab: monthly calendar, chart, weekly records and forecast days.

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

function historyStatusWords(status, day) {
  if (day?.display_label) return day.display_label;
  if (day?.heat_status === "readings") {
    return `Satellite heat readings · ${day.heat_count || 0}`;
  }
  if (day?.heat_status === "checked_empty") {
    return "Checked · no readings returned";
  }
  return ({
    complete: "Available estimate",
    partial: "Partial estimate",
    hidden: "Estimate withheld for validation",
    insufficient: "Insufficient usable coverage",
    not_processed: "Heat readings available · activity estimate not processed",
    future: "Not yet observed",
  })[status] || "No estimate";
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
    const heatDays = [...state.checkedDays.entries()]
      .filter(([, row]) => row && (row.detection_count > 0 || row.status === "heat"))
      .map(([day, row]) => ({
        date: day,
        detection_count: row.detection_count || 0,
        platforms: row.platforms || [],
      }));
    const response = await fetch("/api/history/month", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        coordinates: state.polygon,
        year,
        month: number,
        heat_days: heatDays,
        checked_days: [...state.checkedDays.keys()],
      }),
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
    const notes = [available ? `${historyPercent(rate)} burning activity` : historyStatusWords(record?.activity_status, record)];
    if (available) classes.push(rate > 0 ? "has-activity" : "measured-zero");
    else classes.push("no-estimate");
    if (record?.heat_status === "readings") {
      classes.push("heat");
      notes.push(`${record.heat_count || 0} satellite heat readings`);
    }
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
    const rateText = available
      ? historyPercent(rate)
      : (record?.heat_status === "readings" ? String(record.heat_count || "·") : "—");
    cells.push(
      `<button type="button" class="${classes.join(" ")}" data-day="${iso}" aria-label="${escapeHtml(label)}"`
      + ` aria-pressed="${iso === selected}" style="--activity-strength:${available ? 10 + Math.min(1, Math.max(0, rate)) * 28 : 0}%"`
      + `${disabled ? " disabled" : ""}><span>${day}</span><span class="cal-day-rate">${rateText}</span></button>`
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
  syncMapMode("history");
  state.publicSnapshot = null;
  state.savedExample = false;
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
        : ""}
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
    noteNode.textContent = `${historyStatusWords(record.activity_status, record)}. ${record.estimated_cell_days} of ${record.eligible_cell_days} observed grid squares have a usable estimate for this day.`;
  } else if (state.box) {
    countNode.textContent = record?.heat_status === "readings"
      ? `Satellite heat · ${record.heat_count || 0}`
      : "No estimate";
    noteNode.textContent = historyStatusWords(record?.activity_status, record);
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
  if (state.historyDay) chooseCalendarDay(state.historyDay);
});

document.querySelector("#future-days")?.addEventListener("click", (event) => {
  const day = event.target.closest("[data-forecast-day]");
  if (day) openForecastDay(day.dataset.forecastDay);
});

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

document.querySelector("#week-detail")?.addEventListener("click", (event) => {
  const choice = event.target.closest(".trace-choice");
  if (!choice) return;
  renderTrace(choice.dataset.outcome);
});
