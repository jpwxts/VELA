// Summary card: cutout, weekly burning activity and today's hours.

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
  loadWeeklyActivity();
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
  // Capture into a spare canvas so a superseded capture never paints over a newer one.
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
  // Map tiles keep sharpening after the globe arrives, so take the picture again a few seconds later.
  if (await paint()) window.setTimeout(paint, 5000);
}

// The big figure: Vela's weekly burning-activity estimate for the week that
// holds the observation date. It exists only where weekly history has been
// processed; everywhere else the widget says so instead of showing a number.
async function loadWeeklyActivity() {
  const label = document.querySelector("#activity-label");
  const value = document.querySelector("#activity-value");
  const note = document.querySelector("#activity-note");
  const target = summaryTarget();
  if (!label || !target.box) return;
  const date = dayInput.value;
  const year = date.slice(0, 4);
  const requestId = ++state.activityRequestId;
  const words = (text) => {
    value.textContent = text;
    value.classList.add("is-words");
  };
  label.textContent = "Burning activity";
  words("Loading…");
  note.hidden = false;
  note.textContent = `Reading the weekly estimate for ${formatObservationDay(date)}.`;
  const [west, south, east, north] = target.box;
  let payload;
  try {
    const response = await fetch(`/api/calendar?west=${west}&south=${south}&east=${east}&north=${north}&year=${year}`);
    if (!response.ok) throw new Error("calendar failed");
    payload = await response.json();
  } catch (_error) {
    if (requestId !== state.activityRequestId) return;
    words("Unavailable");
    note.textContent = "The weekly history request failed. Check your connection, then change the date or redraw to try again.";
    return;
  }
  if (requestId !== state.activityRequestId) return;
  const weeks = payload.weeks || [];
  const published = (week) =>
    week.activity_rate != null && (week.activity_status === "complete" || week.activity_status === "partial");
  const week = weeks.find((item) => item.week_start <= date && date <= item.week_end);
  if (week && published(week)) {
    label.textContent = `Burning activity${target.noun === "square" ? " in this square" : ""} · ${formatWeekRange(week.week_start, week.week_end)}`;
    value.textContent = `${(week.activity_rate * 100).toFixed(1)}%`;
    value.classList.remove("is-words");
    note.textContent =
      (week.activity_status === "partial" ? "Partial estimate: some days that week lacked usable coverage. " : "")
      + `How often this ${target.noun}’s grid squares showed burning activity that week. It is not a wildfire probability.`;
    return;
  }
  words("No estimate yet");
  note.textContent = "";
  note.hidden = true;
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

// Start the strip at the current hour so the rest of the day reads left to right.
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

// The strip may be filled while its pane is hidden; place it once it has a real width.
if (window.ResizeObserver && document.querySelector("#hours-strip")) {
  let stripWidth = 0;
  new ResizeObserver((entries) => {
    const width = Math.round(entries[0].contentRect.width);
    if (width && !stripWidth) positionHours();
    stripWidth = width;
  }).observe(document.querySelector("#hours-strip"));
}
