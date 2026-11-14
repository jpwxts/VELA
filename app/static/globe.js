/*
 * Vela globe: a CesiumJS globe drawn as an atlas plate.
 *
 * A night plate: water is deep sea-green, land is dark olive, and real terrain is drawn as
 * contour lines whose spacing follows the zoom. No Cesium ion token is used:
 * the basemap is Esri's keyless light-gray canvas recoloured in the browser,
 * and terrain is Esri's keyless world elevation service.
 *
 * The page scripts (static/js/) talk to the globe only through the object returned by
 * VelaGlobe.create(), so nothing else in the app depends on Cesium.
 */
(function () {
  "use strict";

  const TONE = {
    sea: [19, 43, 42],
    land: [35, 49, 39],
    landLine: [72, 94, 70],
    landLight: [50, 66, 52],
    coast: [112, 148, 106],
    label: [222, 228, 214],
    halo: [14, 22, 19],
  };
  const PLATE = "#0c1311";
  const SEA = "#132b2a";
  const CONTOUR = "#86a87a";

  const BASE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}";
  const LABEL_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}";
  const IMAGERY_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
  const TERRAIN_URL = "https://elevation3d.arcgis.com/arcgis/rest/services/WorldElevation3D/Terrain3D/ImageServer";

  const EARTH_RADIUS = 6371000;
  const MIN_HEIGHT = 1500;
  const MAX_HEIGHT = 40000000;

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  const IMAGERY_CREDIT = "Imagery: Esri, Maxar, Earthstar Geographics";
  const OUTLINE = "#e8ebe1";
  const HEAT = "#ee6540";
  const MARK_EDGE = "#fffdf8";

  /* The cutout's outline and heat marks, shared by the map and satellite pictures.
     `trace` lays the outline path; each spot is a mark already in picture pixels. */
  function paintOutlineAndMarks(context, trace, spots) {
    trace();
    context.lineJoin = "round";
    context.lineWidth = 3;
    context.strokeStyle = OUTLINE;
    context.stroke();
    spots.forEach(({ mark, x, y }) => {
      if (mark.multi) {
        context.beginPath();
        context.arc(x, y, 15, 0, Math.PI * 2);
        context.lineWidth = 3;
        context.strokeStyle = HEAT;
        context.stroke();
      }
      context.beginPath();
      context.arc(x, y, 8, 0, Math.PI * 2);
      context.fillStyle = HEAT;
      context.fill();
      context.lineWidth = 3;
      context.strokeStyle = MARK_EDGE;
      context.stroke();
    });
  }

  /* ---- satellite cutout: imagery tiles drawn straight onto a canvas ----
     It does not use the globe's camera, so the picture is sharp at any size
     and the globe never moves. The tiles are in Web Mercator. */
  const TILE_SIZE = 256;
  const MAX_IMAGERY_ZOOM = 17;

  function worldPixel(lon, lat) {
    const sin = Math.sin((clamp(Number(lat), -85.05, 85.05) * Math.PI) / 180);
    return {
      x: ((Number(lon) + 180) / 360) * TILE_SIZE,
      y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * TILE_SIZE,
    };
  }

  function loadImage(url) {
    return new Promise((resolve) => {
      const image = new Image();
      image.crossOrigin = "anonymous";
      image.onload = () => resolve(image);
      image.onerror = () => resolve(null);
      image.src = url;
    });
  }

  /* Resolves false when no imagery could be loaded. */
  async function satelliteCutout(ring, target, marks) {
    if (!ring || ring.length < 4) return false;
    const corners = ring.map(([lon, lat]) => worldPixel(lon, lat));
    const xs = corners.map((corner) => corner.x);
    const ys = corners.map((corner) => corner.y);
    const ringLeft = Math.min(...xs);
    const ringRight = Math.max(...xs);
    const ringTop = Math.min(...ys);
    const ringBottom = Math.max(...ys);
    if (!(ringRight > ringLeft) || !(ringBottom > ringTop)) return false;
    /* Same rule as the map cutout: heat within half the land's size widens the frame. */
    const reachX = (ringRight - ringLeft) * 0.5;
    const reachY = (ringBottom - ringTop) * 0.5;
    const spots = (marks || [])
      .map((mark) => ({ mark, spot: worldPixel(mark.lon, mark.lat) }))
      .filter(({ spot }) => spot.x > ringLeft - reachX && spot.x < ringRight + reachX
        && spot.y > ringTop - reachY && spot.y < ringBottom + reachY);
    let left = ringLeft;
    let right = ringRight;
    let top = ringTop;
    let bottom = ringBottom;
    spots.forEach(({ spot }) => {
      left = Math.min(left, spot.x);
      right = Math.max(right, spot.x);
      top = Math.min(top, spot.y);
      bottom = Math.max(bottom, spot.y);
    });
    const margin = 18;
    const fit = Math.min((target.width - margin * 2) / (right - left), (target.height - margin * 2) / (bottom - top));
    const shiftX = target.width / 2 - ((left + right) / 2) * fit;
    const shiftY = target.height / 2 - ((top + bottom) / 2) * fit;
    /* The first zoom level whose tiles hold at least as much detail as the picture. */
    const zoom = clamp(Math.ceil(Math.log2(fit)), 0, MAX_IMAGERY_ZOOM);
    const count = 2 ** zoom;
    const span = (TILE_SIZE / count) * fit;
    const tileAt = (value) => Math.floor((value * count) / TILE_SIZE);
    const tiles = [];
    for (let ty = Math.max(0, tileAt(ringTop)); ty <= Math.min(count - 1, tileAt(ringBottom)); ty += 1) {
      for (let tx = tileAt(ringLeft); tx <= tileAt(ringRight); tx += 1) tiles.push({ tx, ty });
    }
    if (!tiles.length || tiles.length > 80) return false;
    const images = await Promise.all(tiles.map(({ tx, ty }) => loadImage(
      IMAGERY_URL.replace("{z}", zoom).replace("{y}", ty).replace("{x}", ((tx % count) + count) % count)
    )));
    if (!images.some(Boolean)) return false;
    const context = target.getContext("2d");
    const trace = () => {
      context.beginPath();
      corners.forEach((corner, index) => {
        const x = corner.x * fit + shiftX;
        const y = corner.y * fit + shiftY;
        if (index) context.lineTo(x, y);
        else context.moveTo(x, y);
      });
      context.closePath();
    };
    context.clearRect(0, 0, target.width, target.height);
    context.save();
    trace();
    context.clip();
    context.imageSmoothingQuality = "high";
    tiles.forEach(({ tx, ty }, index) => {
      /* Half a pixel of overlap hides the hairline seams between tiles. */
      if (images[index]) context.drawImage(images[index], tx * span + shiftX, ty * span + shiftY, span + 0.5, span + 0.5);
    });
    context.restore();
    paintOutlineAndMarks(context, trace, spots.map(({ mark, spot }) => ({
      mark,
      x: spot.x * fit + shiftX,
      y: spot.y * fit + shiftY,
    })));
    return true;
  }

  /* Esri's canvas paints water #d0cfd4 (faintly blue) and land #efefef.
     Water is told apart by being both darker and bluer than land, so neutral
     grey boundary lines stay on the land side and become fine olive lines. */
  function recolourBase(px) {
    const { sea, land, landLine, landLight, coast } = TONE;
    for (let i = 0; i < px.length; i += 4) {
      const r = px[i];
      const g = px[i + 1];
      const b = px[i + 2];
      const lum = 0.299 * r + 0.587 * g + 0.114 * b;
      const tint = b - (r + g) / 2;
      const water = clamp((230 - lum) / 14, 0, 1) * clamp((tint - 0.4) / 1.6, 0, 1);
      const darker = clamp((238 - lum) / 64, 0, 1) * 0.6;
      const lighter = clamp((lum - 241) / 12, 0, 1) * 0.7;
      const edge = (1 - Math.abs(2 * water - 1)) * 0.55;
      for (let c = 0; c < 3; c += 1) {
        let value = land[c] + (landLine[c] - land[c]) * darker + (landLight[c] - land[c]) * lighter;
        value += (sea[c] - value) * water;
        value += (coast[c] - value) * edge;
        px[i + c] = value;
      }
      px[i + 3] = 255;
    }
  }

  /* Reference tiles carry dark text with a white halo on transparency. */
  function recolourLabels(px) {
    const { label, halo } = TONE;
    for (let i = 0; i < px.length; i += 4) {
      const alpha = px[i + 3];
      if (!alpha) continue;
      const light = (0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]) / 255;
      for (let c = 0; c < 3; c += 1) {
        px[i + c] = label[c] + (halo[c] - label[c]) * light;
      }
      px[i + 3] = light > 0.6 ? alpha * 0.5 : alpha;
    }
  }

  /* scale > 1 enlarges the tile with smoothing before recolouring, so the
     water/land split is made on a finer grid and coasts do not stair-step. */
  function loadRecoloured(url, recolour, scale = 1) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.crossOrigin = "anonymous";
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = image.naturalWidth * scale;
        canvas.height = image.naturalHeight * scale;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = "high";
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const data = context.getImageData(0, 0, canvas.width, canvas.height);
        recolour(data.data);
        context.putImageData(data, 0, 0);
        resolve(canvas);
      };
      image.onerror = () => reject(new Error(`Tile failed to load: ${url}`));
      image.src = url;
    });
  }

  function atlasTiles(Cesium, url, recolour, options) {
    const { smoothThroughLevel = -1, ...providerOptions } = options;
    class AtlasTiles extends Cesium.UrlTemplateImageryProvider {
      requestImage(x, y, level) {
        const tileUrl = url.replace("{z}", level).replace("{y}", y).replace("{x}", x);
        return loadRecoloured(tileUrl, recolour, level <= smoothThroughLevel ? 2 : 1);
      }
    }
    return new AtlasTiles({ url, ...providerOptions });
  }

  /* Contour spacing in metres for a camera height in metres. */
  function contourSpacing(height) {
    if (height < 12000) return 20;
    if (height < 40000) return 50;
    if (height < 150000) return 100;
    if (height < 500000) return 250;
    if (height < 1800000) return 500;
    return 1000;
  }

  /* A faint, fixed star field behind the globe. The six faces are drawn once
     from a seeded generator, so the sky is the same on every visit, and
     because it is a real sky box the stars turn as the globe is turned. */
  function starField(Cesium) {
    let seed = 20261114;
    const random = () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
    const face = () => {
      const size = 1024;
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d");
      context.fillStyle = PLATE;
      context.fillRect(0, 0, size, size);
      for (let index = 0; index < 230; index += 1) {
        const bright = random() > 0.93;
        const radius = bright ? 0.9 + random() * 0.5 : 0.45 + random() * 0.4;
        const alpha = bright ? 0.5 + random() * 0.25 : 0.14 + random() * 0.26;
        const tint = random() > 0.7 ? "154, 205, 196" : "232, 235, 225";
        context.fillStyle = `rgba(${tint}, ${alpha.toFixed(2)})`;
        context.beginPath();
        context.arc(4 + random() * (size - 8), 4 + random() * (size - 8), radius, 0, Math.PI * 2);
        context.fill();
      }
      return canvas;
    };
    return new Cesium.SkyBox({
      sources: {
        positiveX: face(),
        negativeX: face(),
        positiveY: face(),
        negativeY: face(),
        positiveZ: face(),
        negativeZ: face(),
      },
    });
  }

  function stubGlobe(container, message) {
    const note = document.createElement("p");
    note.className = "globe-failed";
    note.textContent = message;
    container.append(note);
    const handle = { remove() {}, setVisible() {}, element: null };
    return {
      ready: false,
      onClick() {},
      onView() {},
      flyTo() {},
      home() {},
      zoomBy() {},
      faceNorth() {},
      setInsets() {},
      setBasemap() {},
      screenPosition() { return null; },
      addArea() { return handle; },
      addPath() { return handle; },
      addPoint() { return handle; },
      addRasterOverlay() { return { ...handle, ready: Promise.resolve(false) }; },
      addOverlay(_lat, _lon, element) { return { ...handle, element }; },
      snapshot() { return Promise.resolve(false); },
      satelliteCutout,
      terrainView() { return null; },
    };
  }

  function create(containerId, options = {}) {
    const container = document.getElementById(containerId);
    const Cesium = window.Cesium;
    if (!Cesium) {
      return stubGlobe(
        container,
        "The globe could not load. Vela needs a connection to fetch CesiumJS. Reload once you are online."
      );
    }

    let viewer;
    try {
      viewer = new Cesium.Viewer(container, {
        baseLayer: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        animation: false,
        timeline: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        skyBox: false,
        skyAtmosphere: false,
        creditContainer: options.creditContainer || undefined,
        requestRenderMode: true,
        maximumRenderTimeChange: Infinity,
      });
    } catch (_error) {
      return stubGlobe(
        container,
        "The globe could not start. This browser or device does not offer WebGL, which the 3D globe needs."
      );
    }

    const scene = viewer.scene;
    const camera = scene.camera;
    const globe = scene.globe;
    const canvas = scene.canvas;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const flightSeconds = (seconds) => (reduceMotion ? 0 : seconds);

    /* Draw at the screen's real pixel density (capped at 2x) so coastlines and place names stay crisp. */
    viewer.useBrowserRecommendedResolution = false;
    viewer.resolutionScale = Math.min(window.devicePixelRatio || 1, 2) / (window.devicePixelRatio || 1);
    globe.maximumScreenSpaceError = 1.6;

    scene.backgroundColor = Cesium.Color.fromCssColorString(PLATE);
    try {
      scene.skyBox = starField(Cesium);
    } catch (_error) {
      /* Without the star field the plate stays a plain dark ground. */
    }
    globe.baseColor = Cesium.Color.fromCssColorString(SEA);
    globe.showGroundAtmosphere = false;
    globe.enableLighting = false;
    scene.fog.enabled = false;
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    scene.screenSpaceCameraController.minimumZoomDistance = MIN_HEIGHT;
    scene.screenSpaceCameraController.maximumZoomDistance = MAX_HEIGHT;
    viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

    const layers = scene.imageryLayers;
    const atlasBase = layers.addImageryProvider(atlasTiles(Cesium, BASE_URL, recolourBase, {
      maximumLevel: 16,
      smoothThroughLevel: 6,
      credit: "Basemap: Esri, HERE, Garmin, © OpenStreetMap contributors",
    }));
    const satellite = layers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: IMAGERY_URL,
      maximumLevel: 17,
      credit: "Imagery: Esri, Maxar, Earthstar Geographics",
    }));
    satellite.show = false;
    const atlasLabels = layers.addImageryProvider(atlasTiles(Cesium, LABEL_URL, recolourLabels, {
      maximumLevel: 16,
      credit: "Place names: Esri, © OpenStreetMap contributors",
    }));

    const contourMaterial = new Cesium.Material({
      fabric: {
        type: "VelaContour",
        uniforms: {
          color: Cesium.Color.fromCssColorString(CONTOUR).withAlpha(0.5),
          spacing: 1000.0,
          width: 1.0,
          minHeight: 4.0,
          lowSpacing: 250.0,
          lowCeiling: 1500.0,
        },
        source: `
          uniform vec4 color;
          uniform float spacing;
          uniform float width;
          uniform float minHeight;
          uniform float lowSpacing;
          uniform float lowCeiling;
          czm_material czm_getMaterial(czm_materialInput materialInput) {
            czm_material material = czm_getDefaultMaterial(materialInput);
            float h = materialInput.height;
            float toLine = mod(h, spacing);
            float dxc = abs(dFdx(h));
            float dyc = abs(dFdy(h));
            float band = max(dxc, dyc) * czm_pixelRatio * width;
            /* Skip the sea-level line: coarse terrain smears it offshore as blocky rings. */
            float onLine = (toLine < band && h > max(minHeight, spacing * 0.5)) ? 1.0 : 0.0;
            /* Far out, a finer second interval on lower ground keeps every
               continent in contour lines, not only the high ranges. */
            float toLow = mod(h, max(lowSpacing, 1.0));
            float onLow = (lowSpacing > 0.0 && h < lowCeiling && toLow < band && h > max(minHeight, lowSpacing * 0.5)) ? 0.7 : 0.0;
            material.diffuse = color.rgb;
            material.alpha = max(onLine, onLow) * color.a;
            return material;
          }`,
      },
    });
    globe.material = contourMaterial;

    Cesium.ArcGISTiledElevationTerrainProvider.fromUrl(TERRAIN_URL)
      .then((provider) => {
        viewer.terrainProvider = provider;
        scene.requestRender();
      })
      .catch(() => {
        /* Without terrain the globe stays flat: land and sea still draw, contours do not. */
      });

    /* ---- overlays: HTML markers that follow a point on the globe ---- */
    const overlayLayer = document.createElement("div");
    overlayLayer.className = "globe-overlays";
    container.append(overlayLayer);
    const overlays = new Set();
    const scratch = new Cesium.Cartesian2();

    function placeOverlays() {
      if (!overlays.size) return;
      const occluder = new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84, camera.positionWC);
      overlays.forEach((item) => {
        const visible = occluder.isPointVisible(item.position);
        const spot = visible ? scene.cartesianToCanvasCoordinates(item.position, scratch) : undefined;
        if (!spot) {
          item.element.style.visibility = "hidden";
          return;
        }
        item.element.style.visibility = "visible";
        item.element.style.transform = `translate3d(${spot.x.toFixed(1)}px, ${spot.y.toFixed(1)}px, 0) ${item.anchor}`;
      });
    }
    scene.postRender.addEventListener(placeOverlays);

    const ANCHORS = {
      center: "translate(-50%, -50%)",
      above: "translate(-50%, calc(-100% - 6px))",
      "below-right": "translate(4px, 4px)",
    };

    function addOverlay(lat, lon, element, anchor = "center") {
      element.classList.add("globe-overlay");
      element.style.visibility = "hidden";
      overlayLayer.append(element);
      const item = {
        position: Cesium.Cartesian3.fromDegrees(Number(lon), Number(lat)),
        element,
        anchor: ANCHORS[anchor] || ANCHORS.center,
      };
      overlays.add(item);
      scene.requestRender();
      return {
        element,
        remove() {
          element.remove();
          overlays.delete(item);
        },
      };
    }

    /* ---- lettering: far and mid zoom use the page's own faces ----
       Cities are set in the sans, seas and oceans in tracked italic serif, the
       way a printed atlas letters water. Close in, Esri's label tiles take over
       because they carry every village name. */
    const LABEL_HANDOVER = 1500000;
    const letterLayer = document.createElement("div");
    letterLayer.className = "globe-letters";
    container.insertBefore(letterLayer, overlayLayer);
    let letters = [];
    let lettersOn = true;
    const facingA = new Cesium.Cartesian3();
    const facingB = new Cesium.Cartesian3();
    fetch("/static/gazetteer.json")
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!data) return;
        const make = (entry, kind, order) => {
          const element = document.createElement("span");
          element.className = `map-label ${kind}`;
          element.textContent = entry.n;
          element.style.visibility = "hidden";
          letterLayer.append(element);
          return {
            element,
            kind,
            order,
            position: Cesium.Cartesian3.fromDegrees(entry.lon, entry.lat),
            width: entry.n.length * (kind === "place" ? 6.6 : 9.5) + 10,
          };
        };
        const seas = (data.seas || []).map((entry, index) => make(entry, entry.ocean ? "ocean" : "sea", index));
        const places = (data.places || []).map((entry, index) => make(entry, "place", index));
        /* Water names are placed first so cities yield to them, then cities by population. */
        letters = [...seas, ...places];
        scene.requestRender();
      })
      .catch(() => { /* Without the gazetteer the label tiles still name places close in. */ });

    function updateLabels(height) {
      const authored = lettersOn && height > LABEL_HANDOVER;
      atlasLabels.show = lettersOn && !authored;
      letterLayer.hidden = !authored;
      if (!authored || !letters.length) return;
      const far = height > 6000000;
      const placeLimit = far ? 28 : 110;
      const occluder = new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84, camera.positionWC);
      const taken = [];
      letters.forEach((item) => {
        let show = item.kind === "place" ? item.order < placeLimit : (item.kind === "ocean" || !far || item.order < 16);
        let spot;
        if (show) show = occluder.isPointVisible(item.position);
        /* A name anchored near the limb would run off the disc onto the plate, so it
           must face the camera by a clear angle; wide water names need more room. */
        if (show) {
          const outward = Cesium.Cartesian3.normalize(item.position, facingA);
          const toCamera = Cesium.Cartesian3.normalize(
            Cesium.Cartesian3.subtract(camera.positionWC, item.position, facingB),
            facingB
          );
          show = Cesium.Cartesian3.dot(outward, toCamera) > (item.kind === "place" ? 0.3 : 0.5);
        }
        if (show) {
          spot = scene.cartesianToCanvasCoordinates(item.position, scratch);
          show = Boolean(spot);
        }
        if (show) {
          const box = { left: spot.x - item.width / 2, right: spot.x + item.width / 2, top: spot.y - 10, bottom: spot.y + 10 };
          show = !taken.some((other) =>
            box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top);
          if (show) {
            taken.push(box);
            item.element.style.transform = `translate3d(${spot.x.toFixed(1)}px, ${spot.y.toFixed(1)}px, 0) translate(-50%, -50%)`;
          }
        }
        item.element.style.visibility = show ? "visible" : "hidden";
      });
    }

    /* ---- points: small coloured dots drawn on the canvas ---- */
    const points = scene.primitives.add(new Cesium.PointPrimitiveCollection());

    function addPoint(lat, lon, style = {}) {
      const point = points.add({
        position: Cesium.Cartesian3.fromDegrees(Number(lon), Number(lat)),
        pixelSize: (style.radius || 5) * 2,
        color: Cesium.Color.fromCssColorString(style.fill || "#ee6540"),
        outlineColor: Cesium.Color.fromCssColorString(style.stroke || "#fffdf8"),
        outlineWidth: style.weight == null ? 1.5 : style.weight,
        id: { velaTip: style.tooltip || "", velaClick: style.onClick || null },
      });
      scene.requestRender();
      return {
        remove() {
          points.remove(point);
          scene.requestRender();
        },
        setVisible(visible) {
          point.show = Boolean(visible);
          scene.requestRender();
        },
      };
    }

    /* ---- areas and paths: boundaries draped on the terrain ---- */
    function closedRing(ring) {
      const closed = ring.map(([lon, lat]) => [Number(lon), Number(lat)]);
      const first = closed[0];
      const last = closed[closed.length - 1];
      if (first && (first[0] !== last[0] || first[1] !== last[1])) closed.push([...first]);
      return closed;
    }

    function strokeMaterial(colour, dashed) {
      return dashed
        ? new Cesium.PolylineDashMaterialProperty({ color: colour, dashLength: 14 })
        : colour;
    }

    function addArea(ring, style = {}) {
      const closed = closedRing(ring);
      const positions = Cesium.Cartesian3.fromDegreesArray(closed.flat());
      const stroke = Cesium.Color.fromCssColorString(style.stroke || "#e8ebe1");
      const entities = [];
      if (style.fill) {
        entities.push(viewer.entities.add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions.slice(0, -1)),
            material: Cesium.Color.fromCssColorString(style.fill).withAlpha(style.fillOpacity == null ? 0.1 : style.fillOpacity),
            arcType: Cesium.ArcType.RHUMB,
          },
        }));
      }
      entities.push(viewer.entities.add({
        polyline: {
          positions,
          width: style.weight || 2,
          material: strokeMaterial(stroke, style.dashed),
          clampToGround: true,
          arcType: Cesium.ArcType.RHUMB,
        },
      }));
      scene.requestRender();
      return {
        remove() {
          entities.forEach((entity) => viewer.entities.remove(entity));
          scene.requestRender();
        },
      };
    }

    /* ---- one-tile raster overlays: smoothed backend probability surfaces ---- */
    function addRasterOverlay(canvas, bounds, style = {}) {
      let layer = null;
      let removed = false;
      const rectangle = Cesium.Rectangle.fromDegrees(
        Number(bounds.west),
        Number(bounds.south),
        Number(bounds.east),
        Number(bounds.north)
      );
      const url = canvas.toDataURL("image/png");
      const options = { rectangle };
      const providerPromise = typeof Cesium.SingleTileImageryProvider.fromUrl === "function"
        ? Cesium.SingleTileImageryProvider.fromUrl(url, options)
        : Promise.resolve(new Cesium.SingleTileImageryProvider({ url, ...options }));
      const ready = providerPromise.then((provider) => {
        if (removed) return false;
        /* Under the place names, so they stay readable over the shading. */
        layer = layers.addImageryProvider(provider, layers.indexOf(atlasLabels));
        layer.alpha = style.opacity == null ? 0.62 : Number(style.opacity);
        if (Cesium.TextureMagnificationFilter?.LINEAR) {
          layer.magnificationFilter = Cesium.TextureMagnificationFilter.LINEAR;
        }
        scene.requestRender();
        return true;
      }).catch(() => false);
      return {
        ready,
        remove() {
          removed = true;
          if (layer) layers.remove(layer, true);
          layer = null;
          scene.requestRender();
        },
      };
    }

    function addPath(pathPoints, style = {}) {
      const stroke = Cesium.Color.fromCssColorString(style.stroke || "#e8ebe1");
      const entities = [];
      if (pathPoints.length > 1) {
        entities.push(viewer.entities.add({
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(pathPoints.flat().map(Number)),
            width: style.weight || 2,
            material: strokeMaterial(stroke, style.dashed),
            /* Not draped: a draft line must appear the instant a corner is placed. */
            clampToGround: false,
          },
        }));
      }
      const dots = pathPoints.map(([lon, lat]) => addPoint(lat, lon, {
        radius: 4,
        fill: style.vertexFill || style.stroke || "#e8ebe1",
        stroke: "#0c1311",
        weight: 1.5,
      }));
      scene.requestRender();
      return {
        remove() {
          entities.forEach((entity) => viewer.entities.remove(entity));
          dots.forEach((dot) => dot.remove());
          scene.requestRender();
        },
      };
    }

    /* ---- pointer: clicks, hover tooltips ---- */
    const clickListeners = [];
    const tip = document.createElement("div");
    tip.className = "globe-tip";
    tip.hidden = true;
    container.append(tip);

    function latLonAt(position) {
      const ray = camera.getPickRay(position);
      let cartesian = ray ? globe.pick(ray, scene) : undefined;
      if (!cartesian) cartesian = camera.pickEllipsoid(position, Cesium.Ellipsoid.WGS84);
      if (!cartesian) return null;
      const spot = Cesium.Cartographic.fromCartesian(cartesian);
      return { lat: Cesium.Math.toDegrees(spot.latitude), lon: Cesium.Math.toDegrees(spot.longitude) };
    }

    const pointer = new Cesium.ScreenSpaceEventHandler(canvas);
    pointer.setInputAction((movement) => {
      const picked = scene.pick(movement.position);
      if (picked && picked.id && typeof picked.id.velaClick === "function") {
        picked.id.velaClick();
        return;
      }
      const spot = latLonAt(movement.position);
      if (spot) clickListeners.forEach((listener) => listener(spot));
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    let lastHover = 0;
    pointer.setInputAction((movement) => {
      const now = performance.now();
      if (now - lastHover < 60) return;
      lastHover = now;
      const picked = scene.pick(movement.endPosition);
      const text = picked && picked.id && picked.id.velaTip;
      if (!text) {
        tip.hidden = true;
        canvas.style.cursor = "";
        return;
      }
      tip.textContent = text;
      tip.hidden = false;
      tip.style.transform = `translate3d(${movement.endPosition.x + 14}px, ${movement.endPosition.y + 14}px, 0)`;
      canvas.style.cursor = picked.id.velaClick ? "pointer" : "";
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    canvas.addEventListener("pointerleave", () => { tip.hidden = true; });

    /* ---- keyboard: the globe turns and zooms without a pointer ---- */
    container.tabIndex = 0;
    container.addEventListener("keydown", (event) => {
      if (event.target !== container) return;
      const height = camera.positionCartographic.height;
      const step = clamp((height / EARTH_RADIUS) * 0.18, 0.00002, 0.3);
      const moves = {
        ArrowLeft: () => camera.rotateLeft(step),
        ArrowRight: () => camera.rotateRight(step),
        ArrowUp: () => camera.rotateUp(step),
        ArrowDown: () => camera.rotateDown(step),
        "+": () => zoomBy(0.6),
        "=": () => zoomBy(0.6),
        "-": () => zoomBy(1.6),
      };
      const move = moves[event.key];
      if (!move) return;
      event.preventDefault();
      move();
      scene.requestRender();
    });

    /* ---- camera ---- */
    const insets = { top: 0, right: 0, bottom: 0, left: 0 };
    let flying = false;
    let flightSerial = 0;
    const viewListeners = [];

    function focalPixels() {
      const larger = Math.max(canvas.clientWidth, canvas.clientHeight) || 1;
      return (larger / 2) / Math.tan((camera.frustum.fov || Cesium.Math.toRadians(60)) / 2);
    }

    function homeDestination() {
      const freeWidth = Math.max(240, canvas.clientWidth - insets.right - insets.left);
      const freeHeight = Math.max(240, canvas.clientHeight - insets.top - insets.bottom);
      const focal = focalPixels();
      const radiusPx = 0.43 * Math.min(freeWidth, freeHeight);
      const angle = Math.atan(radiusPx / focal);
      const height = clamp(EARTH_RADIUS / Math.sin(angle) - EARTH_RADIUS, 9000000, MAX_HEIGHT - 2000000);
      const ghost = new Cesium.Camera(scene);
      ghost.setView({ destination: Cesium.Cartesian3.fromDegrees(122, 10, height) });
      /* Look slightly aside so the whole disc sits in the space the card leaves free. */
      const aside = Math.atan(((insets.right - insets.left) / 2) / focal);
      const below = Math.atan(((insets.bottom - insets.top) / 2) / focal);
      if (aside) ghost.lookRight(aside);
      if (below) ghost.lookDown(below);
      return {
        destination: ghost.positionWC.clone(),
        orientation: { direction: ghost.directionWC.clone(), up: ghost.upWC.clone() },
      };
    }

    function home(animate = true) {
      const view = homeDestination();
      if (animate) camera.flyTo({ ...view, duration: flightSeconds(1.4) });
      else camera.setView(view);
      scene.requestRender();
    }

    function flyTo(bounds, flight = {}) {
      let west = Number(bounds.west);
      let east = Number(bounds.east);
      let south = Number(bounds.south);
      let north = Number(bounds.north);
      if (east < west) east += 360;
      const minSpan = flight.minSpan || 0.03;
      if (east - west < minSpan) {
        const middle = (east + west) / 2;
        west = middle - minSpan / 2;
        east = middle + minSpan / 2;
      }
      if (north - south < minSpan) {
        const middle = (north + south) / 2;
        south = middle - minSpan / 2;
        north = middle + minSpan / 2;
      }
      const pad = flight.pad == null ? 0.22 : flight.pad;
      let width = east - west;
      let height = north - south;
      west -= width * pad;
      east += width * pad;
      south -= height * pad;
      north += height * pad;
      width = east - west;
      height = north - south;
      /* Grow the framed rectangle so the land sits in the part of the plate no panel covers. */
      const fullWidth = canvas.clientWidth || 1;
      const fullHeight = canvas.clientHeight || 1;
      const scaleX = fullWidth / Math.max(fullWidth * 0.35, fullWidth - insets.left - insets.right);
      const scaleY = fullHeight / Math.max(fullHeight * 0.35, fullHeight - insets.top - insets.bottom);
      const sideways = insets.left + insets.right || 1;
      const upright = insets.top + insets.bottom || 1;
      east += width * (scaleX - 1) * (insets.right / sideways);
      west -= width * (scaleX - 1) * (insets.left / sideways);
      south -= height * (scaleY - 1) * (insets.bottom / upright);
      north += height * (scaleY - 1) * (insets.top / upright);
      // Set this before flyTo: with reduced motion Cesium can call `complete`
      // synchronously. The serial keeps an older flight's cancel callback from
      // marking a newer flight complete when selections change quickly.
      const thisFlight = ++flightSerial;
      const finishFlight = () => {
        if (thisFlight === flightSerial) flying = false;
      };
      flying = true;
      try {
        camera.flyTo({
          destination: Cesium.Rectangle.fromDegrees(
            clamp(west, -180, 540),
            clamp(south, -89, 89),
            clamp(east, -180, 540),
            clamp(north, -89, 89)
          ),
          duration: flightSeconds(flight.duration == null ? 1.2 : flight.duration),
          complete: finishFlight,
          cancel: finishFlight,
        });
      } catch (error) {
        finishFlight();
        throw error;
      }
      scene.requestRender();
    }

    /* ---- snapshot: the land as a cutout of the plate ----
       Copies what the globe currently shows into `target`, clipped to the
       ring's outline and fitted to the canvas, then marks any heat on top.
       Resolves false when the land is not in view. */
    function drawCutout(ring, target, marks) {
      const project = (lon, lat) => scene.cartesianToCanvasCoordinates(
        Cesium.Cartesian3.fromDegrees(Number(lon), Number(lat)),
        new Cesium.Cartesian2()
      );
      const corners = ring.map(([lon, lat]) => project(lon, lat));
      if (!corners.length || corners.some((corner) => !corner)) return false;
      const xs = corners.map((corner) => corner.x);
      const ys = corners.map((corner) => corner.y);
      let left = Math.min(...xs);
      let top = Math.min(...ys);
      let right = Math.max(...xs);
      let bottom = Math.max(...ys);
      if (right - left < 6 || bottom - top < 6) return false;
      /* Heat just outside the boundary is part of the picture: widen the frame
         to hold marks within half the land's size, and leave farther ones out. */
      const reachX = (right - left) * 0.5;
      const reachY = (bottom - top) * 0.5;
      const spots = (marks || [])
        .map((mark) => ({ mark, spot: project(mark.lon, mark.lat) }))
        .filter(({ spot }) => spot
          && spot.x > left - reachX && spot.x < right + reachX
          && spot.y > top - reachY && spot.y < bottom + reachY);
      spots.forEach(({ spot }) => {
        left = Math.min(left, spot.x - 6);
        right = Math.max(right, spot.x + 6);
        top = Math.min(top, spot.y - 6);
        bottom = Math.max(bottom, spot.y + 6);
      });
      const width = right - left;
      const height = bottom - top;
      const margin = 18;
      const scale = Math.min((target.width - margin * 2) / width, (target.height - margin * 2) / height);
      const shiftX = (target.width - width * scale) / 2 - left * scale;
      const shiftY = (target.height - height * scale) / 2 - top * scale;
      const context = target.getContext("2d");
      const trace = () => {
        context.beginPath();
        corners.forEach((corner, index) => {
          const x = corner.x * scale + shiftX;
          const y = corner.y * scale + shiftY;
          if (index) context.lineTo(x, y);
          else context.moveTo(x, y);
        });
        context.closePath();
      };
      context.clearRect(0, 0, target.width, target.height);
      context.save();
      trace();
      context.clip();
      context.imageSmoothingQuality = "high";
      context.drawImage(
        canvas,
        0, 0, canvas.width, canvas.height,
        shiftX, shiftY, canvas.clientWidth * scale, canvas.clientHeight * scale
      );
      context.restore();
      paintOutlineAndMarks(context, trace, spots.map(({ mark, spot }) => ({
        mark,
        x: spot.x * scale + shiftX,
        y: spot.y * scale + shiftY,
      })));
      return true;
    }

    function snapshot(ring, target, marks) {
      return new Promise((resolve) => {
        const started = performance.now();
        const attempt = () => {
          const settling = flying || !globe.tilesLoaded;
          if (settling && performance.now() - started < 9000) {
            scene.requestRender();
            window.setTimeout(attempt, 250);
            return;
          }
          // Copy in postRender, while this frame's WebGL pixels are still
          // available. Calling render() here can skip drawing in request-render
          // mode, leaving a cleared buffer that looks like a plain outline.
          let removeCapture;
          let captureTimeout;
          const finish = (drawn) => {
            removeCapture();
            window.clearTimeout(captureTimeout);
            points.show = true;
            updateLabels(camera.positionCartographic.height);
            scene.requestRender();
            resolve(drawn);
          };
          removeCapture = scene.postRender.addEventListener(() => {
            let drawn = false;
            try {
              drawn = drawCutout(ring, target, marks);
            } catch (_error) {
              // Keep the existing preview if the browser cannot copy this frame.
            }
            finish(drawn);
          });
          // Hide place labels for this frame only; finish() restores the live
          // globe's current label settings, including after a basemap change.
          atlasLabels.show = false;
          // Globe dots (forecast point, readings) blow up into blobs when a small
          // square is enlarged; heat marks are drawn onto the cutout instead.
          points.show = false;
          captureTimeout = window.setTimeout(() => finish(false), 3000);
          scene.requestRender();
        };
        attempt();
      });
    }

    /* ---- 3D view: a second, small globe that shows one place in relief ----
       Satellite imagery draped on the same terrain, seen at an angle, with the
       outline and heat marks. Drag to turn it. The mouse wheel is left to the
       page so the card still scrolls over it. Returns null without WebGL. */
    function terrainView(host) {
      let inset;
      try {
        inset = new Cesium.Viewer(host, {
          baseLayer: new Cesium.ImageryLayer(new Cesium.UrlTemplateImageryProvider({
            url: IMAGERY_URL,
            maximumLevel: MAX_IMAGERY_ZOOM,
            credit: IMAGERY_CREDIT,
          })),
          baseLayerPicker: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          animation: false,
          timeline: false,
          fullscreenButton: false,
          infoBox: false,
          selectionIndicator: false,
          skyBox: false,
          skyAtmosphere: false,
          creditContainer: options.creditContainer || undefined,
          requestRenderMode: true,
          maximumRenderTimeChange: Infinity,
        });
      } catch (_error) {
        return null;
      }
      const view = inset.scene;
      view.backgroundColor = Cesium.Color.fromCssColorString(PLATE);
      view.globe.baseColor = Cesium.Color.fromCssColorString(SEA);
      view.globe.showGroundAtmosphere = false;
      view.globe.enableLighting = false;
      view.globe.depthTestAgainstTerrain = true;
      if (view.sun) view.sun.show = false;
      if (view.moon) view.moon.show = false;
      view.screenSpaceCameraController.minimumZoomDistance = 150;
      inset.cesiumWidget.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
      const keepWheelForPage = (event) => event.stopPropagation();
      host.addEventListener("wheel", keepWheelForPage, { capture: true });

      const heat = Cesium.Color.fromCssColorString(HEAT);
      const edge = Cesium.Color.fromCssColorString(MARK_EDGE);
      const onGround = Cesium.HeightReference.CLAMP_TO_GROUND;
      let serial = 0;
      let centre = null;
      let range = 1000;

      /* Look at the place from the south at 40 degrees, turning around its centre. */
      function aim(height) {
        const focus = Cesium.Cartesian3.fromRadians(centre.longitude, centre.latitude, height);
        inset.camera.lookAt(focus, new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-40), range));
        view.requestRender();
      }
      /* The outline is measured at sea level; lift the view to the real ground once terrain answers. */
      function aimAtGround(thisSerial) {
        const provider = inset.terrainProvider;
        if (!centre || !provider || provider instanceof Cesium.EllipsoidTerrainProvider) return;
        Cesium.sampleTerrainMostDetailed(provider, [centre.clone()])
          .then(([sample]) => {
            if (thisSerial === serial && !inset.isDestroyed() && sample && Number.isFinite(sample.height)) aim(sample.height);
          })
          .catch(() => {});
      }
      Cesium.ArcGISTiledElevationTerrainProvider.fromUrl(TERRAIN_URL)
        .then((provider) => {
          if (inset.isDestroyed()) return;
          inset.terrainProvider = provider;
          aimAtGround(serial);
          view.requestRender();
        })
        .catch(() => {
          /* Without terrain the imagery still draws, flat. */
        });

      return {
        show(ring, marks) {
          const thisSerial = ++serial;
          inset.entities.removeAll();
          const positions = ring.map(([lon, lat]) => Cesium.Cartesian3.fromDegrees(Number(lon), Number(lat)));
          inset.entities.add({
            polyline: {
              positions,
              width: 2,
              clampToGround: true,
              material: Cesium.Color.fromCssColorString(OUTLINE),
            },
          });
          /* Sizes are screen pixels; the flat pictures draw at twice that, so these are halved to match. */
          (marks || []).forEach((mark) => {
            const position = Cesium.Cartesian3.fromDegrees(Number(mark.lon), Number(mark.lat));
            if (mark.multi) {
              inset.entities.add({
                position,
                point: {
                  pixelSize: 16,
                  color: Cesium.Color.TRANSPARENT,
                  outlineColor: heat,
                  outlineWidth: 1.5,
                  heightReference: onGround,
                  disableDepthTestDistance: Number.POSITIVE_INFINITY,
                },
              });
            }
            inset.entities.add({
              position,
              point: {
                pixelSize: 8,
                color: heat,
                outlineColor: edge,
                outlineWidth: 1.5,
                heightReference: onGround,
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
              },
            });
          });
          const sphere = Cesium.BoundingSphere.fromPoints(positions);
          centre = Cesium.Cartographic.fromCartesian(sphere.center);
          range = Math.max(sphere.radius * 2.6, 800);
          aim(0);
          aimAtGround(thisSerial);
        },
        destroy() {
          serial += 1;
          host.removeEventListener("wheel", keepWheelForPage, { capture: true });
          if (!inset.isDestroyed()) inset.destroy();
        },
      };
    }

    function zoomBy(factor) {
      const here = camera.positionCartographic;
      const height = clamp(here.height * factor, MIN_HEIGHT, MAX_HEIGHT);
      camera.flyTo({
        destination: Cesium.Cartesian3.fromRadians(here.longitude, here.latitude, height),
        orientation: { heading: camera.heading, pitch: camera.pitch, roll: camera.roll },
        duration: flightSeconds(0.35),
      });
      scene.requestRender();
    }

    function viewCentre() {
      return latLonAt(new Cesium.Cartesian2(canvas.clientWidth / 2, canvas.clientHeight / 2));
    }

    function faceNorth() {
      const centre = viewCentre();
      const here = camera.positionCartographic;
      camera.flyTo({
        destination: centre
          ? Cesium.Cartesian3.fromDegrees(centre.lon, centre.lat, here.height)
          : Cesium.Cartesian3.fromRadians(here.longitude, here.latitude, here.height),
        orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
        duration: flightSeconds(0.8),
      });
      scene.requestRender();
    }

    /* Runs every rendered frame: keeps contour spacing matched to the zoom and
       tells listeners (the compass chip) when the view has really moved. */
    let lastSignature = "";
    let lastReport = 0;
    function reportView(force) {
      const height = camera.positionCartographic.height;
      const spacing = contourSpacing(height);
      if (contourMaterial.uniforms.spacing !== spacing) {
        contourMaterial.uniforms.spacing = spacing;
        contourMaterial.uniforms.lowSpacing = spacing >= 1000 ? 250 : spacing >= 500 ? 100 : 0;
        contourMaterial.uniforms.color.alpha = height > 6000000 ? 0.4 : 0.5;
        globe.maximumScreenSpaceError = height > 5000000 ? 1.0 : 1.6;
        scene.requestRender();
      }
      updateLabels(height);
      if (!viewListeners.length) return;
      const now = performance.now();
      if (force !== true && now - lastReport < 120) return;
      const centre = viewCentre();
      const north = centre ? northOnScreen(centre, height) : 0;
      const signature = [
        centre ? centre.lat.toFixed(2) : "x",
        centre ? centre.lon.toFixed(2) : "x",
        north.toFixed(2),
        Math.round(Math.log(height) * 20),
      ].join("|");
      if (force !== true && signature === lastSignature) return;
      lastSignature = signature;
      lastReport = now;
      viewListeners.forEach((listener) => listener({
        lat: centre ? centre.lat : null,
        lon: centre ? centre.lon : null,
        north,
        height,
        contourMetres: spacing,
      }));
    }

    /* Which way north points on screen, in radians clockwise from straight up.
       Measured from two projected points, because camera heading is unstable
       when the camera looks almost straight down. */
    function northOnScreen(centre, height) {
      const step = clamp((height / EARTH_RADIUS) * 8, 0.001, 4);
      const here = scene.cartesianToCanvasCoordinates(
        Cesium.Cartesian3.fromDegrees(centre.lon, centre.lat),
        new Cesium.Cartesian2()
      );
      const northward = scene.cartesianToCanvasCoordinates(
        Cesium.Cartesian3.fromDegrees(centre.lon, clamp(centre.lat + step, -89.9, 89.9)),
        new Cesium.Cartesian2()
      );
      if (!here || !northward) return 0;
      return Math.atan2(northward.x - here.x, here.y - northward.y);
    }
    scene.postRender.addEventListener(() => reportView(false));

    function setBasemap(kind) {
      const atlas = kind !== "satellite";
      atlasBase.show = atlas;
      lettersOn = atlas;
      updateLabels(camera.positionCartographic.height);
      satellite.show = !atlas;
      globe.material = atlas ? contourMaterial : undefined;
      scene.requestRender();
    }

    home(false);

    return {
      ready: true,
      onClick(listener) { clickListeners.push(listener); },
      onView(listener) {
        viewListeners.push(listener);
        reportView(true);
      },
      flyTo,
      home,
      zoomBy,
      faceNorth,
      setInsets(next) {
        Object.assign(insets, { top: 0, right: 0, bottom: 0, left: 0 }, next);
      },
      setBasemap,
      screenPosition(lat, lon) {
        const position = Cesium.Cartesian3.fromDegrees(Number(lon), Number(lat));
        const occluder = new Cesium.EllipsoidalOccluder(Cesium.Ellipsoid.WGS84, camera.positionWC);
        if (!occluder.isPointVisible(position)) return null;
        const spot = scene.cartesianToCanvasCoordinates(position, new Cesium.Cartesian2());
        return spot ? { x: spot.x, y: spot.y } : null;
      },
      addArea,
      addRasterOverlay,
      addPath,
      addPoint,
      addOverlay,
      snapshot,
      satelliteCutout,
      terrainView,
    };
  }

  window.VelaGlobe = { create };
})();
