// Place-name lookup for a selection or a clicked point.

function setPlaceLoading(message = "Looking up place…") {
  const label = document.querySelector("#area-place");
  const meta = document.querySelector("#area-place-meta");
  const coordsRow = document.querySelector("#coords-row");
  const attribution = document.querySelector("#place-attribution");
  label.hidden = false;
  label.textContent = message;
  meta.hidden = true;
  meta.textContent = "";
  coordsRow.hidden = true;
  attribution.hidden = true;
  attribution.textContent = "";
  state.lastPlace = null;
}

function renderPlaceResult(place) {
  const label = document.querySelector("#area-place");
  const meta = document.querySelector("#area-place-meta");
  const coordsRow = document.querySelector("#coords-row");
  const coords = document.querySelector("#area-coords");
  const attribution = document.querySelector("#place-attribution");
  state.lastPlace = place || null;
  if (!place) {
    setPlaceLoading("Place name unavailable.");
    return;
  }
  const text = place.label || place.coordinates_text || "Place name unavailable.";
  label.hidden = false;
  label.textContent = text;
  const relationNotes = {
    inside: "Named place containing this selection",
    near: "Nearest verified named place",
    area_near: "Identified from the square center",
    coordinates: "No reliable place name for this point",
  };
  const note = relationNotes[place.relation] || "";
  meta.hidden = !note;
  meta.textContent = note;
  const showCoords = place.relation === "coordinates" || place.status === "unavailable" || !place.primary;
  coordsRow.hidden = !showCoords;
  if (showCoords) {
    coords.textContent = place.coordinates_text
      || (place.lat != null && place.lon != null ? `${Number(place.lat).toFixed(5)}, ${Number(place.lon).toFixed(5)}` : "");
  }
  const source = place.source || {};
  if (source.attribution) {
    attribution.hidden = false;
    const link = source.url
      ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noopener">${escapeHtml(source.attribution)}</a>`
      : escapeHtml(source.attribution);
    attribution.innerHTML = `${link} · ${escapeHtml(source.name || "Nominatim")}`;
  } else {
    attribution.hidden = true;
  }
  updateSelectionBanner();
  const weatherPlace = document.querySelector("#weather-place");
  if (weatherPlace && place?.label) {
    weatherPlace.hidden = false;
    weatherPlace.textContent = place.label;
  }
}

async function copyPlaceCoordinates() {
  const coords = document.querySelector("#area-coords")?.textContent?.trim();
  if (!coords) return;
  const button = document.querySelector("#copy-coords");
  try {
    await navigator.clipboard.writeText(coords);
    if (button) {
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = "Copy"; }, 1200);
    }
  } catch (_error) {
    if (button) button.textContent = "Copy failed";
  }
}

async function loadPlaceForSelection(spec, requestToken) {
  setPlaceLoading();
  try {
    const response = await fetch("/api/place", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    });
    const payload = await response.json();
    if (requestToken !== state.placeRequestId) return null;
    renderPlaceResult(payload);
    return payload;
  } catch (_error) {
    if (requestToken !== state.placeRequestId) return null;
    renderPlaceResult({
      status: "unavailable",
      relation: "coordinates",
      label: spec.lat != null && spec.lon != null
        ? `${Number(spec.lat).toFixed(5)}, ${Number(spec.lon).toFixed(5)}`
        : "Place lookup failed.",
      coordinates_text: spec.lat != null && spec.lon != null
        ? `${Number(spec.lat).toFixed(5)}, ${Number(spec.lon).toFixed(5)}`
        : "",
      lat: spec.lat,
      lon: spec.lon,
      source: {
        name: "OpenStreetMap Nominatim",
        attribution: "© OpenStreetMap contributors",
        url: "https://www.openstreetmap.org/copyright",
      },
    });
    return null;
  }
}

function beginPlaceLookup(spec) {
  const token = ++state.placeRequestId;
  // Fire without blocking heat readings / satellite details.
  loadPlaceForSelection(spec, token);
  return token;
}

document.querySelector("#copy-coords")?.addEventListener("click", copyPlaceCoordinates);
