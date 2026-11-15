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

function fieldLine(label, field, unit, period) {
  if (!field || field.status === "missing" || field.value == null) {
    return `<li><strong>${escapeHtml(label)}</strong> · missing${period ? ` <span class="quiet">(${escapeHtml(period)})</span>` : ""}</li>`;
  }
  const value = Number(field.value);
  const text = Number.isInteger(value) ? String(value) : value.toFixed(1);
  const zeroNote = field.status === "quiet" && value === 0 ? " (measured zero)" : "";
  return `<li><strong>${escapeHtml(label)}</strong> · ${text} ${escapeHtml(unit)}${zeroNote}${
    period ? ` <span class="quiet">· ${escapeHtml(period)}</span>` : ""
  }</li>`;
}

function windKmhField(day) {
  if (day?.wind_speed_max_km_h?.value != null) return day.wind_speed_max_km_h;
  const ms = day?.wind_speed_max_m_s;
  if (!ms || ms.value == null || ms.status === "missing") return { status: "missing", value: null };
  return { status: ms.status, value: Number((Number(ms.value) * 3.6).toFixed(1)) };
}

function gustKmhField(day) {
  if (day?.wind_gust_max_km_h?.value != null) return day.wind_gust_max_km_h;
  const ms = day?.wind_gust_max_m_s;
  if (!ms || ms.value == null || ms.status === "missing") return { status: "missing", value: null };
  return { status: ms.status, value: Number((Number(ms.value) * 3.6).toFixed(1)) };
}

function dayCardSummary(day) {
  if (day.danger_level) return day.danger_level;
  const fire = day.fire_danger || {};
  if (fire.status === "unavailable" || fire.status === "missing" || fire.fwi == null) {
    return "FWI unavailable";
  }
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
  const coverage = document.querySelector(selectors.coverage);
  const status = document.querySelector(selectors.status);
  const daysHost = document.querySelector(selectors.days);
  const detail = document.querySelector(selectors.detail);
  const meta = document.querySelector(selectors.meta);
  const retry = selectors.retry ? document.querySelector(selectors.retry) : null;
  const fixtureBanner = selectors.fixtureBanner ? document.querySelector(selectors.fixtureBanner) : null;
  const placeNode = document.querySelector("#weather-place");
  const dateNote = document.querySelector("#weather-date-note");
  const regional = document.querySelector("#weather-regional-ref");

  state.forecast = forecast || null;
  if (forecast?.fixture || forecast?.saved) state.savedExample = true;
  // History's calendar and Future list read the same forecast days.
  renderObservationCalendar();
  renderFutureDays();
  const point = forecast?.point || {};
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

  if (dateNote) {
    const obs = document.querySelector("#day")?.value || "";
    const first = forecast?.days?.[0]?.valid_date;
    const last = forecast?.days?.[forecast.days.length - 1]?.valid_date;
    if (first && last) {
      dateNote.hidden = false;
      let text = `Forecast dates (local ${tz}): ${formatShortForecastDay(first, tz)} – ${formatShortForecastDay(last, tz)}.`;
      if (obs && first && obs < first) {
        text += ` Historical hotspot date under review: ${formatObservationDay(obs)} (separate from this outlook).`;
      }
      dateNote.textContent = text;
    } else {
      dateNote.hidden = true;
      dateNote.textContent = "";
    }
  }

  if (regional) {
    const ref = forecast?.regional_fwi_reference;
    if (ref?.url) {
      regional.hidden = false;
      regional.innerHTML =
        `Regional reference (not a numeric Vela reading): <a href="${escapeHtml(ref.url)}" target="_blank" rel="noopener">${escapeHtml(ref.name || "ASMC FWI map")}</a>. `
        + `${escapeHtml(ref.note || "Vela does not infer ratings from map colors.")}`;
    } else {
      regional.hidden = true;
      regional.textContent = "";
    }
  }

  if (!forecast || !(forecast.days || []).length) {
    headline.textContent = "Forecast values unavailable";
    explanation.textContent = "No outlook days were returned for this location.";
    coverage.textContent = "";
    status.textContent = "";
    daysHost.innerHTML = "";
    detail.hidden = true;
    renderWhyThisDay(null);
    if (meta) meta.innerHTML = "";
    if (retry) retry.hidden = false;
    return;
  }

  if (retry) retry.hidden = valuesAvailable;
  headline.textContent = forecast.headline || "Weather outlook";
  explanation.textContent = forecast.headline_explanation || "";
  coverage.textContent =
    forecast.coverage?.text || point.label || "Weather near the center of your selection.";
  status.textContent = forecast.forecast_status?.text || "";

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
    if (!day.danger_level) button.classList.add("fwi-missing");
    button.addEventListener("click", () => showOutlookDay(day, forecast, selectors));
    daysHost.append(button);
  });

  if (meta) meta.innerHTML = outlookMetaHtml(forecast, point, tz);
  renderWhyThisDay(forecast);

  const selected =
    (forecast.days || []).find((day) => day.valid_date === state.selectedForecastDay) ||
    forecast.peak_day ||
    (forecast.days || []).find((day) => day.valid_date === forecast.attention_day) ||
    forecast.days[0];
  // Always fill the detail card when days exist — a blank card next to the strip is a bug.
  if (selected) showOutlookDay(selected, forecast, selectors);
}

function renderWhyThisDay(forecast) {
  const block = document.querySelector("#why-this-day");
  const lead = document.querySelector("#why-this-day-lead");
  const points = document.querySelector("#why-this-day-points");
  const missing = document.querySelector("#why-this-day-missing");
  if (!block || !lead || !points || !missing) return;
  const why = forecast?.why_this_day;
  if (!why?.lead) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  lead.textContent = why.lead;
  points.innerHTML = (why.differences || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  missing.textContent = why.missing_note || "";
}

function outlookMetaHtml(forecast, point, tz = "UTC") {
  const ref = forecast?.regional_fwi_reference;
  return `
    <p><strong>Location</strong> · ${escapeHtml(point.label || "Weather near the center of your selection.")}${
      point.latitude != null
        ? ` (${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)})`
        : ""
    }</p>
    <p><strong>Sources</strong> · Open-Meteo weather · Copernicus GWIS ECMWF Fire Weather Index${
      ref?.url ? ` · regional map reference: ${escapeHtml(ref.name)}` : ""
    }</p>
    <p><strong>Units</strong> · °C, %, km/h, mm · FWI is a unitless index · ranking is a local historical percentile</p>
    <p><strong>Timezone</strong> · ${escapeHtml(tz)}</p>
    <p><strong>Grid</strong> · about ${escapeHtml(String(forecast.grid_resolution_km || 8))} km GWIS cells</p>
    <p><strong>Timing</strong> · ${escapeHtml(forecast.forecast_status?.text || "Issue time unavailable")}</p>
    <p><strong>Class table</strong> · ${escapeHtml(forecast.danger_class_source || "GWIS Fire Danger Classes")}</p>`;
}

function showOutlookDay(day, forecast, selectors) {
  const detail = document.querySelector(selectors.detail);
  const daysHost = document.querySelector(selectors.days);
  state.selectedForecastDay = day.valid_date;
  detail.hidden = false;
  const tz = forecastTimezone(forecast);
  const fire = day.fire_danger || {};
  const fwiAvailable = fire.status === "measured" && fire.fwi != null;
  const fwiText = fwiAvailable
    ? `${Number(fire.fwi).toFixed(1)} (GWIS class: ${day.danger_level || "unclassified"})`
    : "Fire-danger rating unavailable for this day";
  const rankingText =
    fire.ranking == null
      ? "not supplied for this day"
      : `${Number(fire.ranking).toFixed(1)} on the local historical percentile scale (not a wildfire probability)`;
  const wind = windKmhField(day);
  const gust = gustKmhField(day);
  const direction = day.wind_direction_text || null;
  const recent = forecast?.recent_rain || {};
  const ratingNote = day.danger_level
    ? "The rating describes weather that could affect a vegetation fire if one starts. It is not a wildfire probability."
    : "No fire-danger rating was published for this day.";
  detail.innerHTML = `
    <p class="reading-label">${escapeHtml(formatShortForecastDay(day.valid_date, tz))} · Fire-weather danger</p>
    <p class="reading-value">${escapeHtml(day.danger_level || "Not rated")}</p>
    <dl class="stat-grid">
      <div><dt>Temperature</dt><dd>${statText(day.temperature_max_c, "°C")}</dd></div>
      <div><dt>Humidity</dt><dd>${statText(day.relative_humidity_min_percent, "%")}</dd></div>
      <div><dt>Wind</dt><dd>${statText(wind, "km/h")}${
        direction ? `<small>${escapeHtml(direction)}</small>` : ""
      }</dd></div>
      <div><dt>Rain / 24 h</dt><dd>${statText(day.forecast_rain_mm, "mm", 1)}</dd></div>
    </dl>
    ${day.explanation ? `<p>${escapeHtml(day.explanation)}</p>` : ""}
    <p class="quiet">${escapeHtml(pointLabel(forecast))} ${ratingNote}</p>
    <details class="fold">
    <summary>All measurements</summary>
    <ul class="outlook-measures">
      ${fieldLine("Air temperature", day.temperature_max_c, "°C", day.temperature_period || "daily maximum")}
      ${fieldLine("Relative humidity", day.relative_humidity_min_percent, "%", day.humidity_period || "daily minimum")}
      ${fieldLine("Sustained wind", wind, "km/h", day.wind_period || "daily maximum")}
      <li><strong>Wind direction</strong> · ${escapeHtml(direction || "missing")}</li>
      ${fieldLine("Wind gusts", gust, "km/h", day.gust_period || "daily maximum")}
      ${fieldLine("Forecast rainfall", day.forecast_rain_mm, "mm", day.rain_period || "daily total")}
      <li><strong>Recent rainfall</strong> · ${
        recent.millimetres == null
          ? "missing"
          : `${Number(recent.millimetres).toFixed(1)} mm${recent.status === "quiet" ? " (measured zero)" : ""}`
      }${
        recent.start && recent.end
          ? ` <span class="quiet">· ${escapeHtml(recent.start)} to ${escapeHtml(recent.end)}</span>`
          : ""
      }</li>
      <li><strong>Fire Weather Index</strong> · ${escapeHtml(fwiText)}</li>
      <li><strong>Local historical ranking</strong> · ${escapeHtml(rankingText)}</li>
      <li><strong>Source</strong> · ${escapeHtml(forecast?.weather_source || "Open-Meteo")} · FWI ${escapeHtml(
        (fire.source || forecast?.fwi_source || "GWIS").split(".")[0]
      )}</li>
      <li><strong>Valid date</strong> · ${escapeHtml(day.valid_date)} (${escapeHtml(tz)})</li>
      <li><strong>Update / archive time</strong> · ${escapeHtml(
        fire.issue_time || forecast?.forecast_status?.text || "not supplied"
      )}</li>
    </ul>
    </details>`;
  daysHost.querySelectorAll(".day-chip").forEach((node) => {
    const on = node.dataset.date === day.valid_date;
    node.classList.toggle("on", on);
    node.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function pointLabel(forecast) {
  return forecast?.point?.label || "Weather near the center of your selection.";
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
    coverage: "#weather-coverage",
    status: "#weather-status",
    days: "#weather-days",
    detail: "#weather-detail",
    meta: "#weather-meta-body",
    retry: "#weather-retry",
    fixtureBanner: "#weather-fixture-banner",
  };
}

function applyWeatherOutlook(payload) {
  state.selectedForecastDay = null;
  const point = payload.point || {};
  const issued = payload.issued_at || payload.archive_time || null;
  const days = payload.days || [];
  const firstDate = days[0]?.valid_date;
  const lastDate = days[days.length - 1]?.valid_date;
  const obsDate = document.querySelector("#date")?.value || document.querySelector('input[type="date"]')?.value || "";
  let locationText = "Forecast near the center of your plot.";
  if (point.latitude != null && point.longitude != null) {
    locationText =
      `This outlook is a point forecast near the center of the selected land `
      + `(${Number(point.latitude).toFixed(2)}, ${Number(point.longitude).toFixed(2)}).`;
  }
  if (firstDate && lastDate) {
    locationText += ` Outlook covers ${formatObservationDay(firstDate)} to ${formatObservationDay(lastDate)}.`;
  }
  if (issued) {
    locationText += ` Issued/archived ${formatObservationDay(String(issued).slice(0, 10))}.`;
  }
  if (obsDate && firstDate && obsDate < firstDate) {
    locationText +=
      ` You are viewing historical satellite heat from ${formatObservationDay(obsDate)}; the forecast dates above are current outlook dates, not that past day.`;
  }
  document.querySelector("#weather-location").textContent = locationText;
  renderOutlook(payload, weatherSelectors());
  const researchPerf = document.querySelector("#research-performance");
  if (researchPerf) {
    researchPerf.textContent = `Harmonization validation: ${(payload.performance || {}).text || "Pending verification."}`;
  }
}

document.querySelector("#toggle-forecast-point")?.addEventListener("change", (event) => {
  state.showForecastPoint = Boolean(event.target.checked);
  syncForecastMarkerVisibility();
});

document.querySelector("#weather-retry")?.addEventListener("click", () => loadWeatherOutlook({ retry: true }));
