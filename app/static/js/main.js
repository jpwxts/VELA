// Start-up. Loaded last, after every function above exists.

const today = new Date();
today.setDate(today.getDate() - 7);
dayInput.value = today.toISOString().slice(0, 10);
document.querySelector("#year").value = today.getUTCFullYear();
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
  loadStatus();
}

// First paint leaves the globe unobstructed on every screen size.
syncGlobeInsets();

globe.home(false);
setHistoryView(state.historyView);
updateSelectionBanner();
