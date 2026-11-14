// Summary card: cutout, activity %, fire-weather (same as Weather Outlook), heat.

// The land, or the clicked square when one is open.
function summaryTarget() {
  if (state.summarySquare) return { ...state.summarySquare, noun: "square" };
  return { ring: state.polygon, box: state.box, marks: null, noun: "land" };
}

function refreshLandSummary() {
  const section = document.querySelector("#land-summary");
  const hasLand = Boolean(state.polygon && state.polygon.length >= 4);
  state.summarySquare = null;
  document.querySelector("#cell-back").hidden = true;
  document.querySelector("#satellite-picker").hidden = false;
  setSquareHeat(null);
  state.cutoutToken += 1;
  state.activityRequestId += 1;
  state.outlookRequestId += 1;
  section.hidden = !hasLand;
  document.querySelector("#land-secondary-content").hidden = hasLand;
  if (!hasLand) return;
  drawLandCutout([]);
  // While check-land is in flight, show loading — never leave a prior plot’s forecast.
  setLandSummaryLoading();
  loadDayOutlook();
}

// Plain outline of the land, drawn at once so the frame is never empty while
// the globe is still flying to it (and whenever the globe cannot be captured).
function drawLandOutline(ring, canvas) {
  const context = canvas.getContext("2d");
  const lats = ring.map((point) => point[1]);
  const lons = ring.map((point) => point[0]);
  const south = Math.min(...lats);
  const north = Math.max(...lats);
  const west = Math.min(...lons);
  const east = Math.max(...lons);
  const squeeze = Math.cos((((south + north) / 2) * Math.PI) / 180) || 1;
  const width = Math.max((east - west) * squeeze, 1e-6);
  const height = Math.max(north - south, 1e-6);
  const margin = 18;
  const scale = Math.min((canvas.width - margin * 2) / width, (canvas.height - margin * 2) / height);
  const left = (canvas.width - width * scale) / 2;
  const top = (canvas.height - height * scale) / 2;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.beginPath();
  ring.forEach(([lon, lat], index) => {
    const x = left + (lon - west) * squeeze * scale;
    const y = top + (north - lat) * scale;
    if (index) context.lineTo(x, y);
    else context.moveTo(x, y);
  });
  context.closePath();
  context.fillStyle = "#233127";
  context.fill();
  context.lineJoin = "round";
  context.lineWidth = 3;
  context.strokeStyle = LAND_STROKE;
  context.stroke();
}

async function drawLandCutout(areas) {
  const canvas = document.querySelector("#land-cutout");
  const target = summaryTarget();
  const ring = target.ring;
  if (!canvas || !ring || ring.length < 4) return;
  const token = ++state.cutoutToken;
  if (target.marks) areas = [];
  if (!areas.length) drawLandOutline(ring, canvas);
  const marks = target.marks || areas.map((area) => ({
    lat: area.center_lat,
    lon: area.center_lon,
    multi: Boolean(area.multiple_satellites),
  }));
  const spare = document.createElement("canvas");
  spare.width = canvas.width;
  spare.height = canvas.height;
  const paint = async () => {
    if (token !== state.cutoutToken) return false;
    const captured = await globe.snapshot(ring, spare, marks);
    if (!captured || token !== state.cutoutToken) return false;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(spare, 0, 0);
    return true;
  };
  if (await paint()) window.setTimeout(paint, 5000);
}

function setLandSummaryLoading() {
  const activityValue = document.querySelector("#activity-value");
  const activityNote = document.querySelector("#activity-note");
  const reliability = document.querySelector("#activity-reliability");
  document.querySelector("#activity-label").textContent = "Burning activity for this boundary";
  if (activityValue) {
    activityValue.textContent = "Checking…";
    activityValue.classList.add("is-words");
  }
  if (activityNote) {
    activityNote.hidden = false;
    activityNote.textContent = "Loading the harmonized estimate when eligible inputs exist.";
  }
  if (reliability) {
    reliability.hidden = true;
    reliability.textContent = "";
  }
  document.querySelector("#land-fwi-value").textContent = "Loading…";
  document.querySelector("#land-fwi-value").classList.add("is-words");
  document.querySelector("#land-fwi-meta").textContent = "";
  document.querySelector("#land-fwi-drivers").hidden = true;
  document.querySelector("#land-fwi-drivers").innerHTML = "";
  document.querySelector("#land-fwi-note").textContent =
    "Using the same fire-weather outlook as the Weather Outlook tab.";
  document.querySelector("#land-heat-value").textContent = "Checking…";
  document.querySelector("#land-heat-passes").textContent = "";
  document.querySelector("#land-heat-note").textContent = "";
  const showReadings = document.querySelector("#show-readings-on-map");
  if (showReadings) showReadings.hidden = true;
  const combine = document.querySelector("#land-combine");
  if (combine) {
    combine.hidden = true;
    document.querySelector("#land-combine-body").innerHTML = "";
  }
}

function fireWeatherLevel(forecast) {
  if (!forecast) return null;
  if (/^Low throughout/i.test(forecast.headline || "")) return "Low";
  const attention = forecast.attention_day;
  const days = forecast.days || [];
  const match = days.find((day) => day.valid_date === attention) || days.find((day) => day.danger_level);
  return match?.danger_level || null;
}

function fireWeatherDrivers(day) {
  if (!day) return [];
  const lines = [];
  const fire = day.fire_danger || {};
  if (fire.status === "measured" && fire.fwi != null) {
    lines.push(`Fire Weather Index · ${Number(fire.fwi).toFixed(1)}`);
  } else if (fire.status === "unavailable" || fire.status === "missing") {
    lines.push("Fire Weather Index · unavailable");
  }
  const temp = day.temperature_max_c || {};
  if (temp.status !== "missing" && temp.value != null) {
    lines.push(`Air temperature · ${Number(temp.value).toFixed(0)}°C`);
  }
  const humidity = day.relative_humidity_min_percent || {};
  if (humidity.status !== "missing" && humidity.value != null) {
    lines.push(`Relative humidity · ${Number(humidity.value).toFixed(0)}%`);
  }
  const wind = day.wind_speed_max_km_h || day.wind_speed_max_m_s || {};
  if (wind.status !== "missing" && wind.value != null) {
    const kmh = day.wind_speed_max_km_h?.value != null
      ? Number(day.wind_speed_max_km_h.value)
      : Number(day.wind_speed_max_m_s.value) * 3.6;
    lines.push(`Sustained wind · ${kmh.toFixed(1)} km/h`);
  }
  const rain = day.forecast_rain_mm || {};
  if (rain.status !== "missing" && rain.value != null) {
    const zero = rain.status === "quiet" && Number(rain.value) === 0 ? " (measured zero)" : "";
    lines.push(`Forecast rain · ${Number(rain.value).toFixed(1)} mm${zero}`);
  }
  return lines;
}

function applyLandFireWeather(forecast, observationDate) {
  const value = document.querySelector("#land-fwi-value");
  const meta = document.querySelector("#land-fwi-meta");
  const drivers = document.querySelector("#land-fwi-drivers");
  const note = document.querySelector("#land-fwi-note");
  if (!value) return;
  if (!forecast || forecast.ok === false) {
    value.textContent = "Unavailable";
    value.classList.add("is-words");
    meta.textContent = "";
    drivers.hidden = true;
    note.textContent = "Fire-weather outlook could not be loaded for this selection.";
    return;
  }
  const level = fireWeatherLevel(forecast);
  const attention = forecast.attention_day || (forecast.days || [])[0]?.valid_date;
  const day = (forecast.days || []).find((row) => row.valid_date === attention) || (forecast.days || [])[0];
  const point = forecast.point || {};
  if (level) {
    value.textContent = level;
    value.classList.remove("is-words");
    document.querySelector("#land-fwi-label").textContent = `Fire-weather outlook · ${level}`;
  } else {
    value.textContent = "Fire-danger rating unavailable";
    value.classList.add("is-words");
    document.querySelector("#land-fwi-label").textContent = "Fire-weather outlook";
  }
  const pointText = point.latitude != null && point.longitude != null
    ? `Forecast point near selection center (${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)})`
    : (point.label || "Forecast point near the center of your selection.");
  const valid = attention ? `Valid ${formatObservationDay(attention)}` : "";
  const source = (day?.fire_danger?.source || "Copernicus GWIS / Open-Meteo").split(".")[0];
  meta.textContent = [pointText, valid, source].filter(Boolean).join(" · ");
  const lines = fireWeatherDrivers(day);
  drivers.innerHTML = lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("");
  drivers.hidden = lines.length === 0;
  const obs = String(observationDate || dayInput.value || "").slice(0, 10);
  const todayPh = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Manila",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  if (obs && obs < todayPh) {
    note.textContent =
      `Current fire-weather outlook (separate from the historical observation date ${formatObservationDay(obs)}). `
      + "Same response as the Weather Outlook tab.";
  } else {
    note.textContent = "Same fire-weather outlook as the Weather Outlook tab for this selection.";
  }
}

function applyLandActivity(activity, reliability) {
  const label = document.querySelector("#activity-label");
  const value = document.querySelector("#activity-value");
  const note = document.querySelector("#activity-note");
  const reliabilityNode = document.querySelector("#activity-reliability");
  if (!label || !value) return;
  const rate = activity?.activity_rate;
  const denom = activity?.activity_denominator;
  const status = activity?.activity_status;
  if (rate != null && denom != null && (status === "complete" || status === "partial")) {
    label.textContent = status === "partial"
      ? "Estimated activity (partial coverage)"
      : "Estimated activity";
    value.textContent = `${(rate * 100).toFixed(1)}%`;
    value.classList.remove("is-words");
    note.hidden = false;
    note.textContent =
      `Estimated activity across ${denom} observed square${denom === 1 ? "" : "s"}`
      + (activity.week_start && activity.week_end
        ? ` · ${formatWeekRange(activity.week_start, activity.week_end)}`
        : " today")
      + ". "
      + "Activity (%) = 100 × (Aqua indicators + eligible calibrated fallback probabilities) "
      + "÷ square-days with valid contributions. Not burned area and not a wildfire probability.";
    if (reliabilityNode) {
      const mae = reliability?.value_percentage_points;
      reliabilityNode.hidden = false;
      reliabilityNode.innerHTML =
        `<strong>How reliable is this?</strong> `
        + (mae != null
          ? `Weekly activity-share mean absolute error is ${mae} percentage points across four development weeks. `
          : "")
        + (reliability?.philippine_status || "")
        + " Weather-forecast performance is separate from this satellite-model figure.";
    }
    return;
  }
  label.textContent = "Burning activity for this boundary";
  value.textContent = "No estimate yet";
  value.classList.add("is-words");
  note.hidden = false;
  note.textContent = activity?.explanation
    || "No eligible Aqua observations or calibrated Suomi-NPP inputs cover this selection for the selected day, so the denominator is zero.";
  if (reliabilityNode) {
    reliabilityNode.hidden = false;
    reliabilityNode.innerHTML =
      `<strong>How reliable is this?</strong> `
      + (reliability?.plain_language || "")
      + " "
      + (reliability?.philippine_status || "");
  }
}

function distinctHeatPasses(inside) {
  const map = new Map();
  (inside || []).forEach((spot) => {
    const key = `${spot.platform}|${spot.acq_date || ""}|${spot.acq_time || ""}`;
    if (!map.has(key)) {
      map.set(key, {
        platform: spot.platform,
        time_local: spot.acq_time_ph ? `${spot.acq_time_ph} PH time` : formatDetectionLocalTime(spot),
        time_utc: spot.acq_time,
        count: 0,
      });
    }
    map.get(key).count += 1;
  });
  return [...map.values()];
}

function applyLandHeat(heat, observationDate) {
  const value = document.querySelector("#land-heat-value");
  const passes = document.querySelector("#land-heat-passes");
  const note = document.querySelector("#land-heat-note");
  const showReadings = document.querySelector("#show-readings-on-map");
  if (!value) return;
  const inside = heat?.inside || [];
  const status = heat?.status || "";
  const feeds = heat?.feeds || [];
  const unavailable = feeds.filter((row) => row.status === "unavailable" || row.status === "failed");
  if (status === "inside" || inside.length) {
    const platforms = [...new Set(inside.map((row) => row.platform).filter(Boolean))];
    value.textContent = `Heat detected · ${inside.length} reading${inside.length === 1 ? "" : "s"} · ${platforms.join(", ") || "satellite"}`;
    const rows = distinctHeatPasses(inside);
    passes.textContent = rows.map((row) => {
      const local = row.time_local || "";
      const utc = row.time_utc ? `${row.time_utc} UTC` : "";
      return `${row.platform}${local ? ` · ${local}` : ""}${utc ? ` · ${utc}` : ""} · ${row.count} reading${row.count === 1 ? "" : "s"}`;
    }).join(" · ");
    note.textContent =
      `Clipped to your drawn polygon for ${formatObservationDay(observationDate || dayInput.value)} (Asia/Manila calendar day for Philippine plots). `
      + "A missing activity estimate never hides these readings.";
    if (showReadings) showReadings.hidden = false;
  } else if (status === "none_unknown" || heat?.coverage === "unknown") {
    value.textContent = "Checked · no readings returned · coverage unverified";
    passes.textContent = "";
    note.textContent = heat?.lead
      || "The search finished with zero readings inside the boundary. That is not a confirmed clear day.";
    if (showReadings) showReadings.hidden = true;
  } else if (status === "nearby_only") {
    value.textContent = "No heat inside the boundary · nearby readings only";
    passes.textContent = "";
    note.textContent = heat?.lead || "";
    if (showReadings) showReadings.hidden = true;
  } else {
    value.textContent = "Checked · no readings inside the boundary";
    passes.textContent = "";
    note.textContent = heat?.lead || "Completed search with zero returned readings inside the polygon.";
    if (showReadings) showReadings.hidden = true;
  }
  if (unavailable.length) {
    note.textContent = `${note.textContent} Unavailable feeds: ${unavailable.map((row) => row.platform).join(", ")}.`;
  }
}

function applyLandCombine(activity, heat) {
  const host = document.querySelector("#land-combine");
  const body = document.querySelector("#land-combine-body");
  if (!host || !body) return;
  const counts = activity?.method_counts || {};
  const aqua = counts["observed Aqua activity"] || 0;
  const calibrated = counts["calibrated VIIRS estimate"] || 0;
  const raw = counts["raw VIIRS activity"] || 0;
  const unavailable = counts.unavailable || 0;
  const inside = heat?.inside || [];
  const areas = heat?.hotspot_areas?.areas || [];
  const detectionCount = inside.length || heat?.hotspot_areas?.detection_count || 0;
  const multi = heat?.hotspot_areas?.multiple_satellite_area_count || 0;
  host.hidden = false;
  const lines = [];
  if (aqua || calibrated || raw || unavailable) {
    lines.push(`<p><strong>Square-days in the estimate:</strong> Aqua ${aqua} · calibrated Suomi-NPP model ${calibrated} · raw-only ${raw} · calibration-pending/unavailable ${unavailable}.</p>`);
  } else {
    lines.push("<p>No eligible square-days entered the harmonized total for this selection and day.</p>");
  }
  lines.push(
    `<p><strong>Raw detections inside the polygon:</strong> ${detectionCount}`
    + (multi ? ` · ${multi} square${multi === 1 ? "" : "s"} saw 2+ satellites` : "")
    + ". Raw counts stay available even when several satellites observe the same square.</p>"
  );
  if (areas.length) {
    const sample = areas[0];
    const names = (sample.platforms || []).join(", ") || "one satellite";
    lines.push(
      `<p><strong>One square in plain English:</strong> Cell ${escapeHtml(sample.cell_id || "—")} `
      + `had heat from ${escapeHtml(names)} on ${formatObservationDay(sample.observation_day || dayInput.value)}. `
      + "That square contributes at most once per day to the activity percentage.</p>"
    );
  }
  body.innerHTML = lines.join("");
}

function applyLandSummaryFromCheck(payload) {
  if (!payload) return;
  applyLandFireWeather(payload.forecast, payload.observation_date);
  applyLandActivity(payload.activity, payload.reliability);
  applyLandHeat(payload.heat, payload.observation_date);
  applyLandCombine(payload.activity, payload.heat);
}

// Square summary (and date changes) can refresh the activity figure from the
// published calendar without hiding fire-weather already shown from check-land.
async function loadWeeklyActivity() {
  const target = summaryTarget();
  if (!target.box) return;
  const date = dayInput.value;
  const year = date.slice(0, 4);
  const requestId = ++state.activityRequestId;
  const [west, south, east, north] = target.box;
  try {
    const response = await fetch(`/api/calendar?west=${west}&south=${south}&east=${east}&north=${north}&year=${year}`);
    if (!response.ok) throw new Error("calendar failed");
    const payload = await response.json();
    if (requestId !== state.activityRequestId) return;
    const weeks = payload.weeks || [];
    const week = weeks.find((item) => item.week_start <= date && date <= item.week_end);
    if (week && week.activity_rate != null && (week.activity_status === "complete" || week.activity_status === "partial")) {
      applyLandActivity(
        {
          activity_rate: week.activity_rate,
          activity_denominator: week.activity_denominator,
          activity_status: week.activity_status,
          week_start: week.week_start,
          week_end: week.week_end,
          method_counts: week.method_counts,
          explanation: null,
        },
        state.lastLandCheck?.reliability || null
      );
      return;
    }
    applyLandActivity(
      {
        activity_rate: null,
        explanation: state.lastLandCheck?.activity?.explanation
          || "No eligible Aqua observations or calibrated Suomi-NPP inputs cover this selection for the selected day, so the denominator is zero.",
      },
      state.lastLandCheck?.reliability || null
    );
  } catch (_error) {
    if (requestId !== state.activityRequestId) return;
  }
}

// Open-Meteo weather codes (WMO) reduced to seven drawn conditions.
function weatherIcon(code, isDay) {
  const cloud = '<path d="M10.500 22.500h11a4 4 0 0 0 .600-7.960 6 6 0 0 0-11.400-.940 3.600 3.600 0 0 0-.200 8.900Z"/>';
  const high = `<g transform="translate(0 -3)">${cloud}</g>`;
  const sun = '<circle cx="16" cy="16" r="4.600"/><path d="M16 6.500v2.200M16 23.300v2.200M6.500 16h2.200M23.300 16h2.200M9.300 9.300l1.550 1.550M21.150 21.150l1.550 1.550M9.300 22.700l1.550-1.550M21.150 10.850l1.550-1.550"/>';
  const moon = '<path d="M22.500 18.600A8.300 8.300 0 0 1 13.400 9.500a7.300 7.300 0 1 0 9.100 9.100Z"/>';
  const smallSun = '<circle cx="21.500" cy="10.500" r="3"/><path d="M21.500 4.800v1.500M27.200 10.500h-1.500M25.530 6.470l-1.060 1.060M17.470 6.470l1.060 1.060"/>';
  const smallMoon = '<path d="M26 11.300a4.600 4.600 0 0 1-5.300-5.300 4.300 4.300 0 1 0 5.300 5.300Z"/>';
  const wrap = (body) => `<svg viewBox="0 0 32 32" aria-hidden="true">${body}</svg>`;
  if (code == null) return { label: "Conditions missing", svg: wrap('<path d="M11 16h10"/>') };
  if (code === 0 || code === 1) {
    return isDay === false ? { label: "Clear night", svg: wrap(moon) } : { label: "Clear", svg: wrap(sun) };
  }
  if (code === 2) {
    return { label: "Partly cloudy", svg: wrap(`${isDay === false ? smallMoon : smallSun}<g transform="translate(-2 2)">${cloud}</g>`) };
  }
  if (code === 3) return { label: "Cloudy", svg: wrap(cloud) };
  if (code === 45 || code === 48) return { label: "Fog", svg: wrap(`${high}<path d="M9 23.500h14M11.500 27h9"/>`) };
  if (code >= 95) return { label: "Thunderstorm", svg: wrap(`${high}<path d="m16.500 21-2.500 4h3.500l-2 3.500"/>`) };
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) {
    return { label: "Snow", svg: wrap(`${high}<path d="M11.500 24h.01M16 24h.01M20.500 24h.01M13.750 27.500h.01M18.250 27.500h.01" stroke-width="2.200"/>`) };
  }
  if (code >= 51) return { label: "Rain", svg: wrap(`${high}<path d="m12.500 23-1.300 3.500M17 23l-1.300 3.500M21.500 23l-1.300 3.500"/>`) };
  return { label: "Cloudy", svg: wrap(cloud) };
}

async function loadDayOutlook() {
  const target = summaryTarget();
  if (!target.box) return;
  const [west, south, east, north] = target.box;
  const lat = (south + north) / 2;
  const lon = (west + east) / 2;
  const key = `${lat.toFixed(3)},${lon.toFixed(3)}`;
  const requestId = ++state.outlookRequestId;
  if (state.dayOutlook && state.dayOutlookKey === key) {
    renderDayOutlook(state.dayOutlook);
    return;
  }
  document.querySelector("#hours-strip").innerHTML = "";
  document.querySelector("#hours-title").textContent = `Today at this ${target.noun}`;
  document.querySelector("#hours-note").hidden = false;
  document.querySelector("#hours-note").textContent = "Loading today’s temperature and wind…";
  let payload = null;
  try {
    const response = await fetch(`/api/day-outlook?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}`);
    if (response.ok) payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (requestId !== state.outlookRequestId) return;
  if (payload && payload.ok) {
    state.dayOutlook = payload;
    state.dayOutlookKey = key;
  }
  renderDayOutlook(payload);
}

function renderDayOutlook(outlook) {
  const strip = document.querySelector("#hours-strip");
  const title = document.querySelector("#hours-title");
  const note = document.querySelector("#hours-note");
  const noun = summaryTarget().noun;
  if (!outlook || !outlook.ok || !(outlook.slots || []).length) {
    strip.innerHTML = "";
    title.textContent = `Today at this ${noun}`;
    note.hidden = false;
    note.textContent = "Today’s temperature and wind could not be loaded. Vela needs a connection to Open-Meteo for this.";
    updateHoursNav();
    return;
  }
  const step = outlook.step_hours || 3;
  const nowHour = outlook.now ? Number(String(outlook.now).slice(11, 13)) : null;
  title.textContent = `Today at this ${noun} · ${formatShortForecastDay(outlook.date, "UTC")}`;
  strip.innerHTML = outlook.slots.map((slot) => {
    const current = nowHour != null && nowHour >= slot.hour && nowHour < slot.hour + step;
    const icon = weatherIcon(slot.weather_code, slot.is_day);
    const clock = `${String(slot.hour).padStart(2, "0")}:00`;
    const temperature = slot.temperature_c == null ? "—" : `${Math.round(slot.temperature_c)}°`;
    const wind = slot.wind_speed_km_h == null ? "wind missing" : `${Math.round(slot.wind_speed_km_h)} km/h`;
    return `<li class="hour${current ? " now" : ""}">
      <span class="hour-time">${current ? "Now" : clock}</span>
      ${icon.svg}<span class="visually-hidden">${escapeHtml(icon.label)}</span>
      <strong class="hour-temp">${temperature}</strong>
      <span class="hour-wind">${wind}</span>
    </li>`;
  }).join("");
  note.textContent = "";
  note.hidden = true;
  positionHours();
}

function positionHours() {
  const strip = document.querySelector("#hours-strip");
  if (!strip || !strip.clientWidth) return;
  const current = strip.querySelector(".hour.now");
  strip.scrollLeft = current ? Math.max(0, current.offsetLeft - strip.offsetLeft - 14) : 0;
  updateHoursNav();
}

function scrollHours(direction) {
  const strip = document.querySelector("#hours-strip");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  strip.scrollBy({ left: direction * strip.clientWidth, behavior: calm ? "auto" : "smooth" });
}

function updateHoursNav() {
  const strip = document.querySelector("#hours-strip");
  const previous = document.querySelector("#hours-prev");
  const next = document.querySelector("#hours-next");
  if (!strip || !previous || !next) return;
  previous.disabled = strip.scrollLeft <= 2;
  next.disabled = strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 2;
}

document.querySelector("#hours-prev")?.addEventListener("click", () => scrollHours(-1));
document.querySelector("#hours-next")?.addEventListener("click", () => scrollHours(1));
document.querySelector("#hours-strip")?.addEventListener("scroll", updateHoursNav, { passive: true });

document.querySelector("#show-readings-on-map")?.addEventListener("click", () => {
  state.showIndividuals = true;
  const toggle = document.querySelector("#show-individuals");
  if (toggle) toggle.checked = true;
  if (state.lastPayload) renderIndividuals(state.lastPayload);
  document.querySelector("#map-hint").textContent = "Individual satellite readings are shown on the map.";
});

if (window.ResizeObserver && document.querySelector("#hours-strip")) {
  let stripWidth = 0;
  new ResizeObserver((entries) => {
    const width = Math.round(entries[0].contentRect.width);
    if (width && !stripWidth) positionHours();
    stripWidth = width;
  }).observe(document.querySelector("#hours-strip"));
}
