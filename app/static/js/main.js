// Start-up. Loaded last, after every function above exists.
// Live is the default map mode. The observation date follows Asia/Manila today
// unless the visitor opens History or a Saved example.

function manilaTodayIso() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Manila",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function applyLiveDay(phToday) {
  if (!phToday) return;
  state.phToday = phToday;
  if (state.mapMode !== "live") return;
  dayInput.value = phToday;
  document.querySelector("#year").value = phToday.slice(0, 4);
  const clock = document.querySelector("#live-clock");
  if (clock) {
    clock.textContent =
      `Live Philippine date · ${formatObservationDay(phToday)} (Asia/Manila). `
      + "Saved examples never change this.";
  }
}

async function bootLiveClock() {
  try {
    const response = await fetch("/api/live/today");
    if (response.ok) {
      const payload = await response.json();
      applyLiveDay(payload.ph_today || manilaTodayIso());
    } else {
      applyLiveDay(manilaTodayIso());
    }
  } catch (_error) {
    applyLiveDay(manilaTodayIso());
  }
  updateDayWords();
}

// Immediate Asia/Manila today — never seed UTC before Live boots.
applyLiveDay(manilaTodayIso());
initializeHistoryPicker();
updateDayWords();
const bootFixture = new URLSearchParams(location.search).get("fixture");

if (bootFixture === "click_regression" || bootFixture === "two_satellites") {
  loadClickFixture(bootFixture);
} else if (bootFixture === "check_land_demo") {
  loadCompetitionDemo();
} else if (bootFixture === "weather_outlook_amazon" || bootFixture === "weather_values_missing" || bootFixture === "weather_no_fwi") {
  loadStatus();
  loadWeatherFixture(bootFixture);
} else {
  loadStatus().then(() => bootLiveClock());
  // Seed the published Nov 7 snapshot into the durable store (idempotent).
  // Seeding never rewrites Live's observation date.
  fetch("/api/live/seed-snapshot", { method: "POST" }).catch(() => {});
}

// First paint leaves the globe unobstructed on every screen size.
syncGlobeInsets();

globe.home(false);
setHistoryView(state.historyView);
updateSelectionBanner();
setMapMode(state.mapMode || "live");
