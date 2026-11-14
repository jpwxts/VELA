// Shared state, colours and the globe. Loaded first; every other file reads these.

const DEFAULT_PLATFORMS = ["Aqua", "Suomi-NPP", "NOAA-20", "NOAA-21"];

const state = {
  box: null,
  polygon: null,
  polygonDraft: [],
  drawing: false,
  anchor: null,
  rectangle: null,
  polygonLayer: null,
  draftLayer: null,
  forecastMarker: null,
  showForecastPoint: true,
  areaLayers: [],
  individualMarkers: [],
  selectedSquare: null,
  selectedLabel: null,
  lastPayload: null,
  lastLandCheck: null,
  multiOnly: false,
  showIndividuals: false,
  requestId: 0,
  landRequestId: 0,
  weatherRequestId: 0,
  selectedForecastDay: null,
  weeks: [],
  selectedWeek: null,
  revealed: new Map(),
  traces: null,
  forecast: null,
  selectedArea: null,
  detailRequestId: 0,
  ignoreMapClick: false,
  lastActivateToken: "",
  lastActivateAt: 0,
  memberPointLayer: null,
  markerByCell: new Map(),
  landBoundaryLabel: null,
  replayPasses: [],
  replayIndex: 0,
  replayTimer: null,
  placeName: null,
  placeRequestId: 0,
  lastPlace: null,
  panelTab: "where",
  landLabel: null,
  calendarYears: [],
  calendarEmptyReason: null,
  calendarRequestId: 0,
  savedLandSnapshot: null,
  usingSavedExample: false,
  // Atlas shell
  insets: { top: 64, right: 0, bottom: 0, left: 0 },
  basemap: "atlas",
  historyView: "present",
  calendarMonth: null,
  historyDay: null,
  monthHistory: null,
  historyKey: null,
  historyRequestId: 0,
  historyLoading: false,
  historyError: false,
  checkedDays: new Map(),
  checkingDay: null,
  traceOutline: null,
  // Land summary widget
  cutoutToken: 0,
  // A clicked square shown in the summary card instead of the whole land.
  summarySquare: null,
  activityRequestId: 0,
  outlookRequestId: 0,
  dayOutlook: null,
  dayOutlookKey: null,
  publicSnapshot: null,
  pendingMarkerDate: null,
  lastFindings: null,
  savedExample: false,
  mapMode: "live",
  phToday: null,
  liveTimestamps: null,
};

// Ember is reserved for observed heat. The visitor's land is drawn in ink,
// the selected 5 km square in teal, and single satellite readings as ink dots.
const HEAT_FILL = "#ee6540";

const LAND_STROKE = "#e8ebe1";
const CELL_STROKE = "#58b9ad";
const READING_FILL = "#e8ebe1";
const DOT_EDGE = "#0c1311";

const STATUS_TEXT = {
  ok: "Detections returned",
  no_hotspots: "No hotspots returned",
  product_unavailable: "Unavailable for this date",
  request_failed: "Request failed",
  not_configured: "Map key needed",
  area_too_large: "Area too large",
  none_selected: "Select a platform",
};

// The globe is the only map. These scripts never touch Cesium directly; see globe.js.
const globe = VelaGlobe.create("map", { creditContainer: document.querySelector("#globe-credits") });

const dayInput = document.querySelector("#day");
