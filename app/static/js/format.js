// Formatting helpers shared by every part of the page.

function forecastTimezone(forecast) {
  if (state.lastPlace?.country_code === "ph" || state.lastPlace?.timezone === "Asia/Manila") {
    return "Asia/Manila";
  }
  if (forecast?.point?.timezone === "Asia/Manila") return "Asia/Manila";
  return forecast?.point?.timezone || "UTC";
}

function formatDetectionLocalTime(spot) {
  const date = spot.acq_date;
  const time = spot.acq_time || spot.acq_time_raw;
  if (!date || !time) return "—";
  const stamp = `${date}T${String(time).length === 4 ? `${time.slice(0, 2)}:${time.slice(2)}:00` : time}Z`;
  const parsed = new Date(stamp);
  if (Number.isNaN(parsed.getTime())) return `${time} UTC`;
  const tz = forecastTimezone(state.forecast);
  try {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: tz,
    }).format(parsed) + (tz === "Asia/Manila" ? " PH time" : ` ${tz}`);
  } catch (_error) {
    return `${time} UTC`;
  }
}

function formatShortForecastDay(day, timeZone = "UTC") {
  if (!day) return "—";
  const [year, month, dayNumber] = String(day).split("-").map(Number);
  if (!year || !month || !dayNumber) return String(day);
  const date = new Date(Date.UTC(year, month - 1, dayNumber, 12));
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: timeZone || "UTC",
  }).format(date);
}

// One reading for the stat grid: a value with its unit, or the word "Missing".
function statText(field, unit, digits = 0) {
  if (!field || field.status === "missing" || field.value == null) return "Missing";
  const value = Number(field.value).toFixed(digits);
  return unit === "%" ? `${value}%` : `${value} ${escapeHtml(unit)}`;
}

function formatObservationDay(day) {
  if (!day) return "—";
  const [year, month, dayNumber] = String(day).split("-").map(Number);
  if (!year || !month || !dayNumber) return String(day);
  const date = new Date(Date.UTC(year, month - 1, dayNumber));
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

function joinPlatformNames(names) {
  const list = (names || []).filter(Boolean);
  if (!list.length) return "Satellites";
  if (list.length === 1) return list[0];
  if (list.length === 2) return `${list[0]} and ${list[1]}`;
  return `${list.slice(0, -1).join(", ")}, and ${list[list.length - 1]}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

function formatWeekRange(weekStart, weekEnd) {
  const start = new Date(`${weekStart}T00:00:00Z`);
  const end = new Date(`${weekEnd}T00:00:00Z`);
  const startDay = start.getUTCDate();
  const endDay = end.getUTCDate();
  const startMonth = new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(start);
  const endMonth = new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(end);
  if (startMonth === endMonth) return `${startDay}–${endDay} ${startMonth}`;
  return `${startDay} ${startMonth} – ${endDay} ${endMonth}`;
}

function monthLabel(weekStart) {
  const date = new Date(`${weekStart}T00:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" }).format(date);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}
