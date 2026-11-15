// Hotspot readings: every detection's own satellite temperature, fire power and
// surface weather, listed per hotspot in the "Every hotspot" table. A hotspot is
// flagged per satellite pixel, so each value belongs to one pixel — nothing is
// taken from the boundary centre.

const READINGS_TABLE_MAX = 300;
const CONDITIONS_MAX_POINTS = 200;
// VIIRS I4 saturates near 367 K; a reading at that value means "at least this hot".
const VIIRS_I4_SATURATION_K = 367;

state.readingsToken = 0;
state.currentReadings = [];
state.hotspotConditions = new Map();
state.hotspotConditionsPending = new Set();
state.hotspotConditionsFailed = new Set();

function hoursTitle(noun) {
  return noun === "square" ? "Today at this square" : "Today near the center of this land";
}

function readingKey(spot) {
  const time = spot.acq_time || spot.acq_time_raw || "";
  return `${Number(spot.lat).toFixed(5)},${Number(spot.lon).toFixed(5)},${spot.acq_date || ""}T${time},${spot.platform || ""}`;
}

function finiteOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function confidenceWords(value) {
  const text = String(value ?? "").trim().toLowerCase();
  if (!text) return { level: "unknown", label: "—", rank: 0 };
  if (text === "h" || text === "high") return { level: "high", label: "High", rank: 3 };
  if (text === "n" || text === "nominal") return { level: "nominal", label: "Nominal", rank: 2 };
  if (text === "l" || text === "low") return { level: "low", label: "Low", rank: 1 };
  const number = Number(text);
  if (Number.isFinite(number)) {
    // MODIS reports 0–100; FIRMS classes it low < 30, nominal 30–79, high ≥ 80.
    if (number >= 80) return { level: "high", label: `High · ${number}%`, rank: 3 };
    if (number >= 30) return { level: "nominal", label: `Nominal · ${number}%`, rank: 2 };
    return { level: "low", label: `Low · ${number}%`, rank: 1 };
  }
  return { level: "unknown", label: text, rank: 0 };
}

function instrumentOf(spot) {
  const named = String(spot.instrument || "").toUpperCase();
  if (named && named !== "UNKNOWN") return named;
  if (/NOAA|Suomi|NPP/i.test(spot.platform || "")) return "VIIRS";
  if (/Aqua|Terra/i.test(spot.platform || "")) return "MODIS";
  return "";
}

// Philippine detections read in Philippine time; elsewhere the page's local zone.
function readingLocalTime(spot) {
  if (spot.acq_time_ph) return `${spot.acq_time_ph} PH`;
  const lat = Number(spot.lat);
  const lon = Number(spot.lon);
  const inPhilippines = lon >= 116 && lon <= 127.5 && lat >= 4 && lat <= 21.5;
  let time = String(spot.acq_time || spot.acq_time_raw || "");
  if (/^\d{3,4}$/.test(time)) time = time.padStart(4, "0").replace(/^(\d\d)(\d\d)$/, "$1:$2");
  if (inPhilippines && spot.acq_date && /^\d\d:\d\d$/.test(time)) {
    const stamp = new Date(`${spot.acq_date}T${time}:00Z`);
    if (!Number.isNaN(stamp.getTime())) {
      return `${new Intl.DateTimeFormat("en-GB", {
        timeZone: "Asia/Manila", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
      }).format(stamp)} PH`;
    }
  }
  return formatDetectionLocalTime(spot);
}

function detectionReading(spot) {
  const brightnessK = finiteOrNull(spot.brightness);
  const backgroundK = finiteOrNull(spot.bright_2);
  const instrument = instrumentOf(spot);
  return {
    spot,
    key: readingKey(spot),
    platform: spot.platform || "Satellite",
    instrument,
    brightnessK: brightnessK && brightnessK > 0 ? brightnessK : null,
    brightnessC: brightnessK && brightnessK > 0 ? brightnessK - 273.15 : null,
    backgroundC: backgroundK && backgroundK > 0 ? backgroundK - 273.15 : null,
    saturated: Boolean(brightnessK && instrument === "VIIRS" && brightnessK >= VIIRS_I4_SATURATION_K - 0.5),
    frp: finiteOrNull(spot.frp),
    confidence: confidenceWords(spot.confidence),
    daynight: spot.daynight === "D" ? "Day" : spot.daynight === "N" ? "Night" : null,
    when: readingLocalTime(spot),
  };
}

function conditionsFor(reading) {
  if (state.hotspotConditions.has(reading.key)) return state.hotspotConditions.get(reading.key);
  if (state.hotspotConditionsPending.has(reading.key)) return { status: "loading" };
  if (state.hotspotConditionsFailed.has(reading.key)) return { status: "unavailable" };
  return { status: "loading" };
}

function conditionsAirSummary(readings) {
  const rows = readings.map(conditionsFor);
  const ok = rows.filter((row) => row.status === "ok" && row.air_temperature_c != null);
  const loading = rows.some((row) => row.status === "loading");
  return { loading, ok };
}

// ---- rendering --------------------------------------------------------------

function readingsForTarget() {
  const target = summaryTarget();
  const raw = target.noun === "square"
    ? (state.summarySquare?.readings || [])
    : (state.lastLandCheck?.heat?.inside || []);
  return { target, raw };
}

function renderHotspotReadings() {
  const section = document.querySelector("#hotspot-readings");
  if (!section) return;
  const token = ++state.readingsToken;
  const { target, raw } = readingsForTarget();
  if (!raw.length || !(target.ring && target.ring.length >= 4)) {
    section.hidden = true;
    state.currentReadings = [];
    return;
  }
  const readings = raw.map(detectionReading);
  state.currentReadings = readings;
  section.hidden = false;
  document.querySelector("#hotspot-readings-title").textContent = readings.length === 1
    ? "This hotspot’s reading"
    : target.noun === "square" ? "Hotspot readings in this square" : "Hotspot readings in this land";
  renderReadingsTable(readings);
  loadHotspotConditions(readings, token);
}

function conditionCells(reading) {
  const condition = conditionsFor(reading);
  if (condition.status === "loading") {
    return `<td class="num pending" colspan="3">Loading…</td>`;
  }
  if (condition.status !== "ok") {
    return `<td class="num muted" colspan="3">Unavailable</td>`;
  }
  const wind = condition.wind_speed_km_h == null ? "—" : `${Math.round(condition.wind_speed_km_h)}`;
  return `<td class="num">${condition.air_temperature_c == null ? "—" : condition.air_temperature_c.toFixed(1)}</td>
    <td class="num">${condition.relative_humidity_percent == null ? "—" : condition.relative_humidity_percent}</td>
    <td class="num" title="${escapeHtml(condition.wind_direction_text || "")}">${wind}</td>`;
}

function renderReadingsTable(readings) {
  const body = document.querySelector("#hotspot-readings-rows");
  const details = document.querySelector("#hotspot-readings-table");
  const summary = document.querySelector("#hotspot-readings-table-summary");
  if (!body || !details || !summary) return;
  const ordered = readings
    .map((row, index) => ({ row, index }))
    .sort((a, b) => (b.row.brightnessC ?? -Infinity) - (a.row.brightnessC ?? -Infinity)
      || (b.row.frp ?? -Infinity) - (a.row.frp ?? -Infinity));
  const shown = ordered.slice(0, READINGS_TABLE_MAX);
  summary.textContent = readings.length === 1
    ? "Full reading"
    : `Every hotspot (${readings.length}${readings.length > shown.length ? `, first ${shown.length} shown` : ""})`;
  if (readings.length <= 8 && !details.dataset.touched) details.open = true;
  body.innerHTML = shown.map(({ row, index }, rank) => `
    <tr data-reading-index="${index}" tabindex="0" aria-label="${escapeHtml(`Hotspot ${rank + 1}: ${row.platform} at ${row.when}`)}">
      <td><strong>${rank + 1}. ${escapeHtml(row.platform)}</strong><span>${escapeHtml(row.when)}</span></td>
      <td class="num">${row.brightnessC == null ? "—" : `${row.saturated ? "≥" : ""}${row.brightnessC.toFixed(1)}`}</td>
      <td class="num">${row.frp == null ? "—" : row.frp.toFixed(2)}</td>
      <td class="conf conf-${row.confidence.level}" title="${escapeHtml(row.confidence.label)}">${escapeHtml(
        ({ high: "High", nominal: "Nom.", low: "Low" })[row.confidence.level] || "—")}</td>
      ${conditionCells(row)}
    </tr>`).join("");
  const note = document.querySelector("#hotspot-readings-conditions-note");
  if (!note) return;
  const air = conditionsAirSummary(readings);
  note.textContent = air.loading
    ? "Loading air temperature, humidity and wind at each hotspot…"
    : air.ok.length
      ? "Air values: weather model at each hotspot’s own location, at the hour nearest its satellite pass."
      : "Air conditions could not be loaded for these hotspots. The weather service did not answer; satellite readings above are unaffected.";
}

// ---- per-hotspot weather ----------------------------------------------------

async function loadHotspotConditions(readings, token) {
  const wanted = readings
    .filter((row) => !state.hotspotConditions.has(row.key) && !state.hotspotConditionsPending.has(row.key))
    // Hottest first, so the capped request covers the readings that matter most.
    .sort((a, b) => (b.brightnessC ?? -Infinity) - (a.brightnessC ?? -Infinity))
    .slice(0, CONDITIONS_MAX_POINTS);
  readings.forEach((row) => {
    if (!wanted.includes(row) && !state.hotspotConditions.has(row.key) && !state.hotspotConditionsPending.has(row.key)) {
      state.hotspotConditionsFailed.add(row.key);
    }
  });
  if (!wanted.length) {
    if (token === state.readingsToken) renderReadingsTable(state.currentReadings);
    return;
  }
  wanted.forEach((row) => {
    state.hotspotConditionsPending.add(row.key);
    state.hotspotConditionsFailed.delete(row.key);
  });
  let payload = null;
  try {
    const response = await fetch("/api/hotspot-conditions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        points: wanted.map((row) => ({
          id: row.key,
          lat: Number(row.spot.lat),
          lon: Number(row.spot.lon),
          acq_date: String(row.spot.acq_date || ""),
          acq_time: String(row.spot.acq_time || row.spot.acq_time_raw || ""),
        })),
      }),
    });
    if (response.ok) payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  const answered = new Map((payload?.points || []).map((point) => [String(point.id), point]));
  wanted.forEach((row) => {
    state.hotspotConditionsPending.delete(row.key);
    const point = answered.get(row.key);
    if (point && point.status === "ok") state.hotspotConditions.set(row.key, point);
    else state.hotspotConditionsFailed.add(row.key);
  });
  if (token === state.readingsToken) renderReadingsTable(state.currentReadings);
}

// ---- interaction ------------------------------------------------------------

function openReading(index) {
  const reading = state.currentReadings[Number(index)];
  if (!reading) return;
  if (state.currentReadings.length === 1) return;
  showDetection(reading.spot);
}

(function wireReadings() {
  const rows = document.querySelector("#hotspot-readings-rows");
  if (!rows) return;
  rows.addEventListener("click", (event) => {
    const row = event.target.closest("[data-reading-index]");
    if (row) openReading(row.dataset.readingIndex);
  });
  rows.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("[data-reading-index]");
    if (!row) return;
    event.preventDefault();
    openReading(row.dataset.readingIndex);
  });
  document.querySelector("#hotspot-readings-table")?.addEventListener("toggle", (event) => {
    event.currentTarget.dataset.touched = "1";
  });
})();
