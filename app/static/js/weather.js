// Weather outlook tab and the forecast point on the globe.

function clearWeatherOutlook() {
  renderOutlook(null, weatherSelectors());
  const location = document.querySelector("#weather-location");
  if (location) {
    location.textContent =
      "Check your land to load a seven-day outlook near the center of your plot.";
  }
  const banner = document.querySelector("#weather-fixture-banner");
  if (banner) banner.hidden = true;
  const retry = document.querySelector("#weather-retry");
  if (retry) retry.hidden = true;
}

function windKmhField(day) {
  if (day?.wind_speed_max_km_h?.value != null) return day.wind_speed_max_km_h;
  const ms = day?.wind_speed_max_m_s;
  if (!ms || ms.value == null || ms.status === "missing") return { status: "missing", value: null };
  return { status: ms.status, value: Number((Number(ms.value) * 3.6).toFixed(1)) };
}

/** Local historical FWI ranking as a whole-number percent (not a wildfire chance). */
function fireDangerPercent(day) {
  const fire = day?.fire_danger || {};
  const ranking = fire.ranking;
  if (ranking == null || !Number.isFinite(Number(ranking))) return null;
  const value = Number(ranking);
  if (value < 0 || value > 100) return null;
  return Math.round(value);
}

function dayCardSummary(day) {
  const percent = fireDangerPercent(day);
  if (percent != null) return `${percent}%`;
  const fire = day.fire_danger || {};
  if (fire.status === "unavailable" || fire.status === "missing" || fire.fwi == null) {
    return "FWI unavailable";
  }
  if (fire.fwi != null) return `FWI ${Number(fire.fwi).toFixed(1)}`;
  const temp = day.temperature_max_c || {};
  if (temp.status !== "missing" && temp.value != null) {
    return `${Number(temp.value).toFixed(0)}°C`;
  }
  const rain = day.forecast_rain_mm || {};
  if (rain.status !== "missing" && rain.value != null) {
    return `${Number(rain.value).toFixed(1)} mm`;
  }
  return "Weather only";
}

function renderOutlook(forecast, selectors) {
  const headline = document.querySelector(selectors.headline);
  const explanation = document.querySelector(selectors.explanation);
  const status = document.querySelector(selectors.status);
  const daysHost = document.querySelector(selectors.days);
  const detail = document.querySelector(selectors.detail);
  const retry = selectors.retry ? document.querySelector(selectors.retry) : null;
  const fixtureBanner = selectors.fixtureBanner ? document.querySelector(selectors.fixtureBanner) : null;
  const placeNode = document.querySelector("#weather-place");

  state.forecast = forecast || null;
  if (forecast?.fixture || forecast?.saved) state.savedExample = true;
  // History's calendar and Future list read the same forecast days.
  renderObservationCalendar();
  renderFutureDays();
  const tz = forecastTimezone(forecast);
  const valuesAvailable = forecast?.values_available !== false && (forecast?.days || []).some((day) => {
    const fire = day.fire_danger || {};
    return (
      (fire.status === "measured" && fire.fwi != null) ||
      ["temperature_max_c", "forecast_rain_mm", "wind_speed_max_m_s", "relative_humidity_min_percent"].some((key) => {
        const field = day[key] || {};
        return field.status !== "missing" && field.value != null;
      })
    );
  });

  if (placeNode) {
    const placeLabel =
      state.lastPlace?.label
      || state.placeName
      || state.landLabel
      || document.querySelector("#selection-place")?.textContent
      || "";
    placeNode.hidden = !placeLabel || placeLabel === "Selected land";
    placeNode.textContent = placeLabel;
  }

  if (fixtureBanner) {
    if (forecast?.fixture?.label || forecast?.saved) {
      fixtureBanner.hidden = false;
      fixtureBanner.textContent = forecast.fixture?.label || "Saved weather fixture";
    } else {
      fixtureBanner.hidden = true;
    }
  }

  if (!forecast || !(forecast.days || []).length) {
    headline.textContent = "Forecast values unavailable";
    explanation.textContent = "No outlook days were returned for this location.";
    status.textContent = "";
    daysHost.innerHTML = "";
    detail.hidden = true;
    if (retry) retry.hidden = false;
    return;
  }

  if (retry) retry.hidden = valuesAvailable;
  // A loaded outlook speaks through the day strip and the day card alone.
  headline.textContent = valuesAvailable ? "" : "Forecast values unavailable";
  explanation.textContent = "";
  status.textContent = "";

  daysHost.innerHTML = "";
  (forecast.days || []).forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day-chip";
    button.dataset.date = day.valid_date;
    button.setAttribute("aria-pressed", "false");
    const summary = valuesAvailable ? dayCardSummary(day) : "No values";
    const peak = day.valid_date === forecast.attention_day ? " · peak" : "";
    button.innerHTML = `<span class="day-date">${escapeHtml(
      formatShortForecastDay(day.valid_date, tz)
    )}</span><span class="day-level">${escapeHtml(summary + peak)}</span>`;
    if (!valuesAvailable) button.disabled = true;
    if (day.valid_date === forecast.attention_day) button.classList.add("peak");
    const fire = day.fire_danger || {};
    if (fireDangerPercent(day) == null && fire.fwi == null) button.classList.add("fwi-missing");
    button.addEventListener("click", () => showOutlookDay(day, forecast, selectors));
    daysHost.append(button);
  });

  const selected =
    (forecast.days || []).find((day) => day.valid_date === state.selectedForecastDay) ||
    forecast.peak_day ||
    (forecast.days || []).find((day) => day.valid_date === forecast.attention_day) ||
    forecast.days[0];
  // Always fill the detail card when days exist — a blank card next to the strip is a bug.
  if (selected) showOutlookDay(selected, forecast, selectors);
}

function showOutlookDay(day, forecast, selectors) {
  const detail = document.querySelector(selectors.detail);
  const daysHost = document.querySelector(selectors.days);
  state.selectedForecastDay = day.valid_date;
  detail.hidden = false;
  const tz = forecastTimezone(forecast);
  const fire = day.fire_danger || {};
  const fwiAvailable = fire.status === "measured" && fire.fwi != null;
  const percent = fireDangerPercent(day);
  const wind = windKmhField(day);
  const direction = day.wind_direction_text || null;
  const reading = percent != null
    ? `${percent}%`
    : (fwiAvailable ? `FWI ${Number(fire.fwi).toFixed(1)}` : "Not rated");
  detail.innerHTML = `
    <p class="reading-label">${escapeHtml(formatShortForecastDay(day.valid_date, tz))} · Fire-weather danger</p>
    <p class="reading-value">${escapeHtml(reading)}</p>
    <p class="quiet reading-sub">${
      percent != null
        ? `Local historical FWI ranking${day.danger_level ? ` · GWIS class was ${escapeHtml(day.danger_level)}` : ""}`
        : (day.danger_level ? `GWIS class ${escapeHtml(day.danger_level)}` : "")
    }</p>
    <dl class="stat-grid">
      <div><dt>Temperature</dt><dd>${statText(day.temperature_max_c, "°C")}</dd></div>
      <div><dt>Humidity</dt><dd>${statText(day.relative_humidity_min_percent, "%")}</dd></div>
      <div><dt>Wind</dt><dd>${statText(wind, "km/h")}${
        direction ? `<small>${escapeHtml(direction)}</small>` : ""
      }</dd></div>
      <div><dt>Rain / 24 h</dt><dd>${statText(day.forecast_rain_mm, "mm", 1)}</dd></div>
    </dl>`;
  daysHost.querySelectorAll(".day-chip").forEach((node) => {
    const on = node.dataset.date === day.valid_date;
    node.classList.toggle("on", on);
    node.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function syncForecastMarkerVisibility() {
  if (!state.forecastMarker) return;
  state.forecastMarker.setVisible(state.showForecastPoint !== false);
}

function forecastHasUsefulValues(forecast) {
  return Boolean(
    forecast
    && (forecast.days || []).some((day) => {
      const fire = day.fire_danger || {};
      return (
        (fire.status === "measured" && fire.fwi != null)
        || ["temperature_max_c", "forecast_rain_mm", "wind_speed_max_m_s", "relative_humidity_min_percent"].some((key) => {
          const field = day[key] || {};
          return field.status !== "missing" && field.value != null;
        })
      );
    })
  );
}

async function loadWeatherOutlook(options = {}) {
  const location = document.querySelector("#weather-location");
  const retry = document.querySelector("#weather-retry");
  if (!state.box) {
    renderOutlook(null, weatherSelectors());
    document.querySelector("#weather-headline").textContent = "No land selected yet";
    document.querySelector("#weather-explanation").textContent =
      "Search for a place or draw a boundary on the globe to see its fire-weather outlook.";
    location.textContent = "Check your land to load a seven-day outlook near the center of your plot.";
    if (retry) retry.hidden = true;
    return;
  }
  const cached =
    state.forecast
    || state.lastLandCheck?.forecast
    || state.lastPayload?.forecast
    || null;
  const preferCached =
    !options.retry
    && cached
    && (cached.saved || cached.fixture || forecastHasUsefulValues(cached));
  if (preferCached) {
    applyWeatherOutlook(cached);
    return;
  }
  const [west, south, east, north] = state.box;
  const requestId = ++state.weatherRequestId;
  location.textContent = `Loading outlook near the center of your plot (${west}, ${south} to ${east}, ${north})…`;
  document.querySelector("#weather-headline").textContent = "Loading forecast…";
  document.querySelector("#weather-explanation").textContent =
    "An older response will not replace this outlook.";
  try {
    const response = await fetch(
      `/api/preparedness?west=${west}&south=${south}&east=${east}&north=${north}`
    );
    const payload = await response.json();
    if (requestId !== state.weatherRequestId) return;
    applyWeatherOutlook(payload);
  } catch (error) {
    if (requestId !== state.weatherRequestId) return;
    renderOutlook(null, weatherSelectors());
    document.querySelector("#weather-headline").textContent = "Forecast values unavailable";
    document.querySelector("#weather-explanation").textContent = "The forecast request failed.";
    if (retry) retry.hidden = false;
  }
}

async function loadWeatherFixture(name) {
  const requestId = ++state.weatherRequestId;
  try {
    const response = await fetch(`/api/preparedness/fixture?name=${encodeURIComponent(name)}`);
    const payload = await response.json();
    if (requestId !== state.weatherRequestId) return;
    if (payload.bbox) {
      const box = payload.bbox;
      setBox([box.west, box.south, box.east, box.north], payload.fixture?.label || "Weather fixture area");
      setPolygonFromBox(state.box, payload.fixture?.label || "Weather fixture area");
    }
    state.forecast = payload;
    applyWeatherOutlook(payload);
    openLandPanel({ tab: "weather", focus: false });
  } catch (error) {
    if (requestId !== state.weatherRequestId) return;
    document.querySelector("#weather-headline").textContent = "Forecast values unavailable";
    document.querySelector("#weather-explanation").textContent = "Weather fixture failed to load.";
  }
}

function weatherSelectors() {
  return {
    headline: "#weather-headline",
    explanation: "#weather-explanation",
    status: "#weather-status",
    days: "#weather-days",
    detail: "#weather-detail",
    retry: "#weather-retry",
    fixtureBanner: "#weather-fixture-banner",
  };
}

function applyWeatherOutlook(payload) {
  state.selectedForecastDay = null;
  // The loaded outlook needs no location or issue-time line.
  document.querySelector("#weather-location").textContent = "";
  renderOutlook(payload, weatherSelectors());
}

document.querySelector("#toggle-forecast-point")?.addEventListener("change", (event) => {
  state.showForecastPoint = Boolean(event.target.checked);
  syncForecastMarkerVisibility();
});

document.querySelector("#weather-retry")?.addEventListener("click", () => loadWeatherOutlook({ retry: true }));
