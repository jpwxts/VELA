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

async function loadHotspotMonthForSquare(cellId, yearMonth) {
  if (!cellId || !yearMonth) return;
  const requestId = (state.hotspotMonthRequestId = (state.hotspotMonthRequestId || 0) + 1);
  state.hotspotMonthCellId = cellId;
  state.hotspotMonthKey = `${cellId}|${yearMonth}`;
  try {
    const params = new URLSearchParams({ cell_id: cellId, year_month: yearMonth });
    const response = await fetch(`/api/hotspot-forecast/month?${params}`);
    const payload = await response.json();
    if (requestId !== state.hotspotMonthRequestId) return;
    if (state.hotspotMonthKey !== `${cellId}|${yearMonth}`) return;
    state.hotspotMonth = payload;
    renderObservationCalendar();
  } catch (_error) {
    if (requestId !== state.hotspotMonthRequestId) return;
    state.hotspotMonth = null;
  }
}

// Stored daily estimates drive both the month calendar and the chart. A gap
// always stays missing; it is never inferred from an empty live FIRMS result.
// When an evaluated Mindanao square is selected, heat-chance % overlay day cells
// for issued/reconstructed dates only — never for Upcoming future days.
// Burning activity stays a separate calendar mode (not the hotspot %).
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
  // Heat-only days shade by their share of this month's busiest day.
  const heatPeak = Math.max(1, ...(payload?.days || []).map((day) => (
    day.heat_status === "readings" ? Number(day.heat_count) || 0 : 0)));
  const hotspotDays = new Map((state.hotspotMonth?.days || []).map((day) => [day.date, day]));
  const forecastMode = Boolean(state.hotspotMonthCellId && state.hotspotMonth?.days?.length);
  if (state.hotspotMonthCellId && state.hotspotMonth?.year_month !== state.calendarMonth) {
    loadHotspotMonthForSquare(state.hotspotMonthCellId, state.calendarMonth);
  }
  const cells = ["S", "M", "T", "W", "T", "F", "S"].map(
    (letter) => `<span class="cal-weekday" aria-hidden="true">${letter}</span>`
  );
  for (let blank = 0; blank < first.getUTCDay(); blank += 1) cells.push("<span></span>");
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const record = daily.get(iso);
    const hotspot = hotspotDays.get(iso);
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
    let rateText = available
      ? historyPercent(rate)
      : (record?.heat_status === "readings" ? String(record.heat_count || "·") : "—");
    if (forecastMode && hotspot) {
      classes.push("forecast");
      if (hotspot.calendar_state === "upcoming" || iso > today) {
        classes.push("forecast-upcoming");
        rateText = "Upcoming";
        notes.push("Upcoming — no issued percentage yet");
      } else if (hotspot.probability_percent != null) {
        classes.push(hotspot.issuance_kind === "historical_reconstruction" ? "forecast-reconstructed" : "forecast-issued");
        rateText = `${hotspot.probability_percent}%`;
        notes.push(
          `${hotspot.probability_percent}% chance satellites record a hotspot (${hotspot.issuance_kind || "forecast"})`
        );
      } else if (hotspot.calendar_state === "insufficient_inputs") {
        classes.push("forecast-insufficient");
        rateText = "—";
        notes.push(hotspot.reason || "hotspot forecast insufficient inputs");
      } else if (hotspot.calendar_state === "coverage_status_only") {
        classes.push("forecast-insufficient");
        rateText = "Cov";
        notes.push(hotspot.reason || "Mindanao coverage/readings only — percentage not evaluated here yet");
      } else if (hotspot.calendar_state === "unsupported_location") {
        rateText = "—";
        notes.push(hotspot.reason || "outside Mindanao study area");
      }
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
      + ` aria-pressed="${iso === selected}" style="--activity-strength:${available ? 10 + Math.min(1, Math.max(0, rate)) * 28 : 0}%;`
      + `--heat-strength:${record?.heat_status === "readings" ? Math.round(14 + ((Number(record.heat_count) || 0) / heatPeak) * 46) : 0}%"`
      + `${disabled ? " disabled" : ""}><span>${day}</span><span class="cal-day-rate">${rateText}</span></button>`
    );
  }
  grid.innerHTML = cells.join("");
  const status = document.querySelector("#history-status");
  const published = (payload?.days || []).filter((day) => day.activity_rate != null).length;
  const hotspotPublished = (state.hotspotMonth?.days || []).filter((day) => day.probability_percent != null).length;
  const upcomingCount = (state.hotspotMonth?.days || []).filter((day) => day.calendar_state === "upcoming").length;
  const activityKey = document.querySelector("#history-activity-key");
  const forecastKey = document.querySelector("#history-forecast-key");
  if (activityKey) activityKey.hidden = forecastMode;
  if (forecastKey) forecastKey.hidden = !forecastMode;
  const daysLabel = document.querySelector("#history-days-label");
  if (daysLabel) {
    daysLabel.textContent = forecastMode ? "Days with forecasts" : "Days with activity estimates";
  }
  const activityStat = document.querySelector("#history-activity-stat");
  if (activityStat) activityStat.hidden = forecastMode;
  status.textContent = state.historyLoading ? "Loading burning activity…"
    : state.historyError ? "History could not be loaded. Please try again."
    : forecastMode ? ""
    : !state.box ? "Select land to see its burning history."
    : published ? `${published} of ${daysInMonth} days have usable estimates. Select a day for details.`
    : `No burning-activity estimates for ${title.textContent}.`;
  status.hidden = !status.textContent;
  document.querySelector("#history-retry").hidden = !state.historyError;
  // Never put a single-day forecast percent under “Month's activity”.
  document.querySelector("#history-month-rate").textContent = forecastMode
    ? "—"
    : historyPercent(payload?.summary?.activity_rate);
  document.querySelector("#history-days-count").textContent = state.historyLoading
    ? "…"
    : forecastMode
      ? `${hotspotPublished} / ${daysInMonth}`
      : `${published} / ${daysInMonth}`;
  const firstObservation = payload?.first_observation;
  document.querySelector("#history-availability").textContent = firstObservation
    ? `Stored observations for this land: ${formatObservationDay(firstObservation)} – ${formatObservationDay(payload.last_observation)}.`
    : "";
  renderHistoryChart();
  renderDaySummary();
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

function historyHotspotForDay(iso) {
  return (state.hotspotMonth?.days || []).find((entry) => entry.date === iso) || null;
}

// Each series returns raw values (a count, or a 0–1 share) so the axis, average,
// peak and table all read the same numbers.
function historyChartSeries(rows, annual) {
  const hasActivity = rows.some((row) => typeof row.activity_rate === "number" && Number.isFinite(row.activity_rate));
  if (hasActivity) {
    return {
      kind: "activity",
      title: "Burning activity history",
      valueOf: (row) => (Number.isFinite(row.activity_rate) ? row.activity_rate : null),
      format: (value) => historyPercent(value),
      axisFormat: (value) => `${Math.round(value * 100)}%`,
      valueHeading: "Burning activity",
      empty: "No burning-activity estimates for this period",
      percent: true,
    };
  }
  const forecastMode = !annual && Boolean(state.hotspotMonthCellId && state.hotspotMonth?.days?.length);
  const hasForecast = forecastMode && rows.some((row) => {
    const hotspot = historyHotspotForDay(row.date);
    return hotspot && hotspot.probability_percent != null;
  });
  if (hasForecast) {
    return {
      kind: "hotspot",
      title: "Hotspot chance history",
      valueOf: (row) => {
        const hotspot = historyHotspotForDay(row.date);
        return hotspot?.probability_percent != null ? hotspot.probability_percent / 100 : null;
      },
      format: (value) => `${Math.round(value * 100)}%`,
      axisFormat: (value) => `${Math.round(value * 100)}%`,
      valueHeading: "Hotspot chance",
      empty: "No hotspot forecasts for this period",
      percent: true,
    };
  }
  const hasHeat = !annual && rows.some((row) => row.heat_status === "readings" && (row.heat_count || 0) > 0);
  if (hasHeat) {
    return {
      kind: "heat",
      title: "Satellite heat readings",
      // Checked-and-empty is a measured zero only when coverage was observed; an empty
      // FIRMS answer with unknown coverage stays a gap, never an inferred zero.
      valueOf: (row) => (row.heat_status === "readings"
        ? (Number(row.heat_count) || 0)
        : row.heat_status === "checked_empty" && row.heat_coverage === "observed" ? 0 : null),
      format: (value) => `${Math.round(value)} reading${Math.round(value) === 1 ? "" : "s"}`,
      axisFormat: (value) => (value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}K` : `${value}`),
      valueHeading: "Heat readings",
      empty: "No heat readings for this period",
      count: true,
    };
  }
  return {
    kind: "empty",
    title: "Burning activity history",
    valueOf: () => null,
    format: () => "—",
    axisFormat: (value) => `${Math.round(value * 100)}%`,
    valueHeading: "Value",
    empty: state.historyLoading ? "Loading history…" : state.historyError ? "Could not load history" : "No estimates for this period",
    percent: true,
  };
}

// Round axis maxima to 1 / 2 / 2.5 / 5 × 10ⁿ so tick labels stay clean.
function historyNiceAxis(maximum, { count = false, percent = false } = {}) {
  if (!(maximum > 0)) return { top: percent ? 0.1 : 4, step: percent ? 0.05 : 1 };
  const raw = maximum / 4;
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  let step = (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10) * power;
  if (count) step = Math.max(1, Math.ceil(step));
  if (percent) step = Math.max(0.01, step);
  let top = Math.ceil(maximum / step - 1e-9) * step;
  if (percent) top = Math.min(1, top);
  return { top: Math.max(step, top), step };
}

// Column path: square at the baseline, 4px rounded data end.
function historyColumnPath(x, bottom, width, height) {
  const radius = Math.min(4, width / 2, height);
  const top = bottom - height;
  return `M${x},${bottom}V${top + radius}Q${x},${top} ${x + radius},${top}`
    + `H${x + width - radius}Q${x + width},${top} ${x + width},${top + radius}V${bottom}Z`;
}

function historyRowLabel(key, annual) {
  return annual ? monthLabel(`${key}-01`) : formatObservationDay(key);
}

// Totals, averages and peaks the chart draws from: computed once, shown as tiles,
// as the average line, as the peak label, and in the data table.
function historyChartStats(series, rows, annual) {
  const today = todayIso();
  const keyOf = (row) => (annual ? row.month : row.date);
  const elapsed = rows.filter((row) => (annual ? keyOf(row) <= today.slice(0, 7) : keyOf(row) <= today));
  const points = elapsed
    .map((row) => ({ row, key: keyOf(row), value: series.valueOf(row) }))
    .filter((point) => typeof point.value === "number" && Number.isFinite(point.value));
  if (!points.length) return { points, elapsed: elapsed.length, count: 0 };
  const values = points.map((point) => point.value);
  const total = values.reduce((sum, value) => sum + value, 0);
  const peak = points.reduce((best, point) => (point.value > best.value ? point : best), points[0]);
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  // Second half against first half of the observed points: a direction, not a forecast.
  let trend = null;
  if (points.length >= 4) {
    const half = Math.floor(points.length / 2);
    const early = points.slice(0, half).reduce((sum, point) => sum + point.value, 0) / half;
    const late = points.slice(points.length - half).reduce((sum, point) => sum + point.value, 0) / half;
    trend = { early, late };
  }
  return {
    points,
    elapsed: elapsed.length,
    count: points.length,
    total,
    mean: total / points.length,
    median,
    peak,
    trend,
  };
}

function historyTrendWords(series, trend) {
  if (!trend) return null;
  const { early, late } = trend;
  if (early === 0 && late === 0) return "Flat";
  if (early === 0) return "Rising from zero";
  const change = (late - early) / early;
  if (Math.abs(change) < 0.1) return "About level";
  const size = `${Math.round(Math.abs(change) * 100)}%`;
  return change > 0 ? `Up ${size}` : `Down ${size}`;
}

function renderHistoryChartStats(series, stats, annual) {
  const host = document.querySelector("#history-chart-stats");
  if (!host) return;
  if (!stats.count) {
    host.innerHTML = "";
    host.hidden = true;
    return;
  }
  const unit = annual ? "month" : "day";
  const tile = (label, value, sub) => `<div><dt>${escapeHtml(label)}</dt><dd><strong>${escapeHtml(value)}</strong>${
    sub ? `<span>${escapeHtml(sub)}</span>` : ""}</dd></div>`;
  const peakWhen = annual
    ? new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(new Date(`${stats.peak.key}-01T00:00:00Z`))
    : formatObservationDay(stats.peak.key);
  const trend = historyTrendWords(series, stats.trend);
  const tiles = [];
  if (series.kind === "heat") {
    tiles.push(tile("Total readings", stats.total.toLocaleString("en-GB"), `${stats.count} of ${stats.elapsed} ${unit}s with heat`));
    tiles.push(tile("Peak day", `${Math.round(stats.peak.value)}`, peakWhen));
    tiles.push(tile("Average", stats.mean.toFixed(1), `per heat ${unit} · median ${stats.median}`));
  } else {
    tiles.push(tile("Average", series.format(stats.mean), `${stats.count} of ${stats.elapsed} ${unit}s with ${series.kind === "hotspot" ? "forecasts" : "estimates"}`));
    tiles.push(tile(`Peak ${unit}`, series.format(stats.peak.value), peakWhen));
    tiles.push(tile("Median", series.format(stats.median), `across ${stats.count} ${unit}${stats.count === 1 ? "" : "s"}`));
  }
  tiles.push(tile("Trend", trend || "Too few points", trend ? `later vs earlier ${unit}s` : "Needs 4 or more"));
  host.innerHTML = tiles.join("");
  host.hidden = false;
}

function renderHistoryChartTable(series, rows, annual) {
  const body = document.querySelector("#history-chart-data-rows");
  const details = document.querySelector("#history-chart-data");
  if (!body || !details) return;
  const today = todayIso();
  const keyOf = (row) => (annual ? row.month : row.date);
  const listed = rows.filter((row) => (annual ? keyOf(row) <= today.slice(0, 7) : keyOf(row) <= today));
  document.querySelector("#history-chart-data-period").textContent = annual ? "Month" : "Day";
  document.querySelector("#history-chart-data-value").textContent = series.valueHeading;
  details.hidden = series.kind === "empty" || !listed.length;
  body.innerHTML = listed.map((row) => {
    const value = series.valueOf(row);
    const available = typeof value === "number" && Number.isFinite(value);
    const status = series.kind === "heat"
      ? (row.heat_area_count ? `${row.heat_area_count} squares` : (available ? "" : "No readings stored"))
      : historyStatusWords(row.activity_status, row);
    return `<tr><td>${escapeHtml(historyRowLabel(keyOf(row), annual))}</td>`
      + `<td class="num">${available ? escapeHtml(series.format(value)) : "—"}</td>`
      + `<td>${escapeHtml(status || "")}</td></tr>`;
  }).join("");
}

function renderHistoryChart() {
  const svg = document.querySelector("#history-chart");
  if (!svg) return;
  hideHistoryChartTip();
  const payload = currentMonthHistory();
  const annual = document.querySelector("#history-chart-range").value === "year";
  const selectedMonth = state.calendarMonth || todayIso().slice(0, 7);
  const [year, month] = selectedMonth.split("-").map(Number);
  const rows = annual
    ? payload?.months || Array.from({ length: 12 }, (_, index) => ({ month: `${year}-${String(index + 1).padStart(2, "0")}` }))
    : payload?.days || Array.from({ length: new Date(Date.UTC(year, month, 0)).getUTCDate() }, (_, index) => ({ date: `${selectedMonth}-${String(index + 1).padStart(2, "0")}` }));
  const monthName = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, 1)));
  const series = historyChartSeries(rows, annual);
  state.historyChart = { series, rows, annual };
  const titleNode = document.querySelector("#history-chart-title");
  if (titleNode) titleNode.textContent = series.title;
  document.querySelector("#history-chart-caption").textContent = annual
    ? `Monthly burning activity in ${year}. Select a bar to open that month.`
    : series.kind === "hotspot"
      ? `Daily hotspot chance for square ${state.hotspotMonthCellId} in ${monthName}. Not burning activity.`
      : series.kind === "heat"
        ? `Satellite heat readings inside this land each day of ${monthName}. Select a bar to see that day.`
        : `Daily burning activity in ${monthName}. Select a bar to see that day.`;
  const description = document.querySelector("#history-chart-description");
  if (description) {
    description.textContent = series.kind === "hotspot"
      ? ""
      : series.kind === "heat"
        ? "Each bar counts the individual satellite detections stored for that Philippine day. Burning-activity estimates are not processed for these days yet."
        : "Percentages use observed grid squares with usable estimates. Empty periods have no estimate.";
    description.hidden = !description.textContent;
  }

  const stats = historyChartStats(series, rows, annual);
  renderHistoryChartStats(series, stats, annual);
  renderHistoryChartTable(series, rows, annual);

  const left = 34;
  const right = 328;
  const top = 26;
  const bottom = 166;
  const height = bottom - top;
  const band = (right - left) / rows.length;
  // 2px surface gap between neighbours; never wider than 24px.
  const barWidth = Math.max(2, Math.min(24, band - 2));
  const axis = historyNiceAxis(stats.count ? stats.peak.value : 0, { count: series.count, percent: series.percent });
  const yOf = (value) => bottom - (Math.max(0, value) / axis.top) * height;
  const today = todayIso();
  const parts = [];

  for (let tick = 0; tick <= axis.top + 1e-9; tick += axis.step) {
    const y = yOf(tick);
    parts.push(`<line class="history-chart-grid${tick === 0 ? " baseline" : ""}" x1="${left}" y1="${y}" x2="${right}" y2="${y}"/>`
      + `<text class="history-chart-axis" x="${left - 6}" y="${y + 3}" text-anchor="end">${escapeHtml(series.axisFormat(Number(tick.toFixed(4))))}</text>`);
  }

  rows.forEach((row, index) => {
    const key = annual ? row.month : row.date;
    const future = annual ? key > today.slice(0, 7) : key > today;
    const isToday = !annual && key === today;
    const value = series.valueOf(row);
    const available = typeof value === "number" && Number.isFinite(value);
    const x = left + index * band;
    const barX = x + (band - barWidth) / 2;
    const selected = annual ? key === selectedMonth : key === (state.historyDay || dayInput.value);
    const isPeak = stats.count && stats.peak.key === key;
    const label = annual
      ? new Intl.DateTimeFormat("en-GB", { month: "narrow", timeZone: "UTC" }).format(new Date(`${key}-01T00:00:00Z`))
      : String(index + 1);
    const words = available ? series.format(value) : historyStatusWords(row.activity_status, row);
    const descriptionText = `${historyRowLabel(key, annual)}: ${words}`;
    const attributes = future
      ? `data-history-index="${index}"`
      : `role="button" tabindex="0" data-history-index="${index}" data-history-${annual ? "month" : "day"}="${key}" aria-label="${escapeHtml(descriptionText)}"`;
    let mark = "";
    if (available && value > 0) {
      const barHeight = Math.max(2, bottom - yOf(value));
      mark = `<path class="history-chart-value ${series.kind}" d="${historyColumnPath(barX, bottom, barWidth, barHeight)}"/>`;
    } else if (available) {
      // A measured zero: a hairline on the baseline, distinct from a missing day.
      mark = `<rect class="history-chart-value zero" x="${barX}" y="${bottom - 1.5}" width="${barWidth}" height="1.5"/>`;
    } else if (!future) {
      mark = `<circle class="history-chart-missing" cx="${x + band / 2}" cy="${bottom - 2}" r="1"/>`;
    }
    const showLabel = annual || index === 0 || (index + 1) % 5 === 0 || index === rows.length - 1 || selected || isToday;
    parts.push(`<g class="history-chart-bar${selected ? " selected" : ""}${future ? " future" : ""}${row.activity_status === "partial" ? " partial" : ""}" ${attributes}>
      <rect class="history-chart-hit" x="${x}" y="${top - 8}" width="${band}" height="${bottom - top + 26}"/>
      ${mark}
      ${showLabel ? `<text class="history-chart-axis${selected ? " selected" : ""}${isToday ? " today" : ""}" x="${x + band / 2}" y="${bottom + 13}" text-anchor="middle">${escapeHtml(label)}</text>` : ""}
    </g>`);
    if (isPeak && value > 0) {
      const peakX = Math.min(right - 8, Math.max(left + 8, x + band / 2));
      parts.push(`<text class="history-chart-peak" x="${peakX}" y="${yOf(value) - 5}" text-anchor="middle">${escapeHtml(series.kind === "heat" ? String(Math.round(value)) : series.format(value))}</text>`);
    }
  });

  // Average reference line across observed periods.
  if (stats.count >= 2 && stats.mean > 0) {
    const y = yOf(stats.mean);
    const text = `avg ${series.kind === "heat" ? stats.mean.toFixed(1) : series.format(stats.mean)}`;
    parts.push(`<line class="history-chart-mean" x1="${left}" y1="${y}" x2="${right}" y2="${y}"/>`
      + `<text class="history-chart-mean-label" x="${right}" y="${y - 4}" text-anchor="end">${escapeHtml(text)}</text>`);
  }

  if (!stats.count) {
    parts.push(`<text class="history-chart-empty" x="${(left + right) / 2}" y="${(top + bottom) / 2}" text-anchor="middle">${escapeHtml(series.empty)}</text>`);
  }
  svg.innerHTML = parts.join("");
  const key = document.querySelector("#history-chart-key");
  if (key) {
    key.hidden = !stats.count;
    key.innerHTML = stats.count
      ? `<span class="key-swatch ${series.kind}"></span>${escapeHtml(series.valueHeading)}`
        + (stats.count >= 2 ? `<span class="key-line"></span>Average` : "")
        + `<span class="key-dot-missing"></span>No data`
      : "";
  }
}

function hideHistoryChartTip() {
  const tip = document.querySelector("#history-chart-tip");
  if (tip) tip.hidden = true;
}

function showHistoryChartTip(group) {
  const tip = document.querySelector("#history-chart-tip");
  const frame = document.querySelector("#history-chart-frame");
  const chart = state.historyChart;
  if (!tip || !frame || !chart) return;
  const row = chart.rows[Number(group.dataset.historyIndex)];
  if (!row) return;
  const key = chart.annual ? row.month : row.date;
  const value = chart.series.valueOf(row);
  const available = typeof value === "number" && Number.isFinite(value);
  const future = chart.annual ? key > todayIso().slice(0, 7) : key > todayIso();
  tip.replaceChildren();
  const line = (text, className) => {
    if (!text) return;
    const node = document.createElement("p");
    if (className) node.className = className;
    node.textContent = text;
    tip.append(node);
  };
  line(available ? chart.series.format(value) : future ? "Not yet" : "No data", "tip-value");
  line(historyRowLabel(key, chart.annual), "tip-label");
  if (chart.series.kind === "heat" && available) {
    line([
      row.heat_area_count ? `${row.heat_area_count} squares with heat` : null,
      (row.heat_platforms || row.platforms || []).length ? joinPlatformNames(row.heat_platforms || row.platforms) : null,
    ].filter(Boolean).join(" · "));
  } else if (!available && !future) {
    line(historyStatusWords(row.activity_status, row));
  } else if (row.activity_status === "partial") {
    line("Partial estimate");
  }
  if (!future) line(chart.annual ? "Select to open this month" : "Select to see this day", "tip-note");
  tip.hidden = false;
  const frameBox = frame.getBoundingClientRect();
  const markBox = (group.querySelector(".history-chart-value") || group.querySelector(".history-chart-hit")).getBoundingClientRect();
  const tipBox = tip.getBoundingClientRect();
  let leftPx = markBox.left - frameBox.left + markBox.width / 2 - tipBox.width / 2;
  leftPx = Math.max(0, Math.min(frameBox.width - tipBox.width, leftPx));
  let topPx = markBox.top - frameBox.top - tipBox.height - 8;
  if (topPx < 0) topPx = 0;
  tip.style.left = `${leftPx}px`;
  tip.style.top = `${topPx}px`;
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
  const hotspot = (state.hotspotMonth?.days || []).find((entry) => entry.date === iso);
  const forecastMode = Boolean(state.hotspotMonthCellId && state.hotspotMonth?.days?.length);
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
  } else if (forecastMode && hotspot?.probability_percent != null) {
    countNode.textContent = `${hotspot.probability_percent}%`;
    const board = hotspot.model_board?.models || [];
    const boardLine = board.length
      ? ` Models: ${board.map((row) => `${row.name} ${row.probability_percent}%`).join(" · ")}.`
      : "";
    const claim = hotspot.evaluation?.claimable_holdout || hotspot.model_board?.evaluation?.claimable_holdout || {};
    const evalLine = claim.accuracy != null
      ? ` Claimable holdout Acc ${(Number(claim.accuracy) * 100).toFixed(0)}% · Brier ${Number(claim.brier_score).toFixed(3)} (not this day’s accuracy).`
      : "";
    noteNode.textContent = `Chance satellites record a hotspot (${hotspot.issuance_kind || "forecast"}).${boardLine}${evalLine} Burning activity is separate.`;
  } else if (forecastMode && hotspot?.calendar_state === "coverage_status_only") {
    countNode.textContent = "Coverage only";
    noteNode.textContent = hotspot.reason || "Readings and weather available; percentage not evaluated for this Mindanao tile yet.";
  } else if (forecastMode && hotspot?.calendar_state === "upcoming") {
    countNode.textContent = "Upcoming";
    noteNode.textContent = "No heat-chance percentage until that Philippine date.";
  } else if (record?.activity_rate != null) {
    countNode.textContent = historyPercent(record.activity_rate);
    noteNode.textContent = `${historyStatusWords(record.activity_status, record)}. ${record.estimated_cell_days} of ${record.eligible_cell_days} observed grid squares have a usable estimate for this day.`;
  } else if (state.box) {
    countNode.textContent = record?.heat_status === "readings"
      ? `Satellite heat · ${record.heat_count || 0}`
      : "No burning activity found";
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
  list.innerHTML = days.map((day) => {
    const percent = typeof fireDangerPercent === "function" ? fireDangerPercent(day) : null;
    const fire = day.fire_danger || {};
    const label = percent != null
      ? `${percent}%`
      : (fire.fwi != null ? `FWI ${Number(fire.fwi).toFixed(1)}` : "Not rated");
    return `<li><button type="button" class="future-day" data-forecast-day="${escapeHtml(day.valid_date)}">
      <span>${escapeHtml(formatShortForecastDay(day.valid_date, tz))}</span>
      <strong>${escapeHtml(label)}</strong>
    </button></li>`;
  }).join("");
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
document.querySelector("#history-chart")?.addEventListener("pointermove", (event) => {
  const group = event.target.closest("[data-history-index]");
  if (group) showHistoryChartTip(group);
  else hideHistoryChartTip();
});
document.querySelector("#history-chart")?.addEventListener("pointerleave", hideHistoryChartTip);
document.querySelector("#history-chart")?.addEventListener("focusin", (event) => {
  const group = event.target.closest("[data-history-index]");
  if (group) showHistoryChartTip(group);
});
document.querySelector("#history-chart")?.addEventListener("focusout", hideHistoryChartTip);

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
