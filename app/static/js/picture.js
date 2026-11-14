// The card's picture of the land or square: map, satellite imagery or a 3D view.

// The picture shows on every tab whenever there is drawn land or an open square.
function syncLandPicture() {
  const shown = Boolean(state.summarySquare || (state.polygon && state.polygon.length >= 4));
  document.querySelector("#land-picture").hidden = !shown;
  // The other tabs read the whole land, so say so while a square is in the picture.
  document.querySelector("#picture-note").hidden = !(state.summarySquare && state.panelTab !== "where");
  if (!shown) closeTerrainView();
}

function setPictureCredit(text) {
  const credit = document.querySelector("#picture-credit");
  credit.textContent = text;
  credit.hidden = !text;
}

// Swap between the flat picture (map or satellite) and the 3D view.
function showPictureStyle(mode, noun) {
  const canvas = document.querySelector("#land-cutout");
  canvas.hidden = mode === "3d";
  document.querySelector("#land-3d").hidden = mode !== "3d";
  canvas.setAttribute(
    "aria-label",
    mode === "satellite" ? `Satellite imagery of the selected ${noun}` : `The selected ${noun}, cut out of the map`
  );
  // Imagery and terrain credits are in the map legend; this line is kept for load errors.
  setPictureCredit("");
}

function showTerrainView(ring, marks) {
  if (!state.terrainView) state.terrainView = globe.terrainView(document.querySelector("#land-3d"));
  if (!state.terrainView) {
    document.querySelector("#land-3d").hidden = true;
    document.querySelector("#land-cutout").hidden = false;
    setPictureCredit("The 3D view could not start in this browser. Map and Satellite still work.");
    return;
  }
  state.terrainView.show(ring, marks);
}

// The 3D view is a second globe; free it whenever it is out of sight.
function closeTerrainView() {
  if (!state.terrainView) return;
  state.terrainView.destroy();
  state.terrainView = null;
}

function setPictureMode(mode) {
  if (mode === state.pictureMode) return;
  state.pictureMode = mode;
  document.querySelectorAll("[data-picture]").forEach((button) => {
    const on = button.dataset.picture === mode;
    button.classList.toggle("on", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
  });
  drawLandCutout(state.pictureAreas);
}

document.querySelectorAll("[data-picture]").forEach((button) => {
  button.addEventListener("click", () => setPictureMode(button.dataset.picture));
});
