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
  const previousDay = dayInput.value;
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
  if (state.mapMode === "live") updateDayWords({ skipCheck: previousDay === dayInput.value });
}

// Immediate Asia/Manila today — never seed UTC before Live boots.
applyLiveDay(manilaTodayIso());
initializeHistoryPicker();
updateDayWords();
const bootFixture = new URLSearchParams(location.search).get("fixture");

const activityExample = new URLSearchParams(location.search).get("example");
if (["activity-pilot", "activity-zero", "activity-missing"].includes(activityExample)) {
  loadStatus().then(() => {
    syncMapMode("history");
    dayInput.value=activityExample==="activity-zero"?"2024-03-09":activityExample==="activity-missing"?"2024-03-02":"2024-03-11";
    updateDayWords({skipCheck:true});
    setPolygonFromBox([123.6,6.3,124.7,7.4],"Maguindanao activity pilot");
    checkLand({date:dayInput.value,forceDate:true});
  });
} else if (bootFixture === "click_regression" || bootFixture === "two_satellites") {
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
