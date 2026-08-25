(function () {
'use strict';

/* Resolves relative to the page URL by default (matches the original
   standalone layout, where index.html sits next to data/). The Django
   integration overrides this via window.RIGA_DATA_BASE_URL to point at
   the app's static folder instead. */
var DATA_BASE_URL = window.RIGA_DATA_BASE_URL || "data/";

/* ═══════════════════════════════════════════════════
   DATA & FILTER STATE
═══════════════════════════════════════════════════ */
var allData = null;
var buildingsLayer = null;
var renderToken = 0;
var RENDER_CHUNK_SIZE = 450;
var CLASS_ORDER = ["A+","A","B","C","D","E","F"];
var CLASS_SET = new Set(CLASS_ORDER);
var activeClasses = new Set(CLASS_ORDER);
var searchIndex = [];
var searchControl = null;
var searchInputEl = null;
var searchResultsEl = null;
var REGION_ORDER = [];
var activeRegions = new Set();
var regionPolygons = [];
var REGION_COLORS = ["#5b8ff9", "#61ddaa", "#f6bd16", "#f08bb4", "#7262fd", "#78d3f8", "#9fb4cb"];
var activeYearMin = null;
var activeYearMax = null;
var activeRenovationFilter = "all"; // "all" | "renovated" | "unrenovated"

function normalizeEnergyClass(value) {
  if (typeof value !== "string") return null;
  var cls = value.trim().toUpperCase();
  return CLASS_SET.has(cls) ? cls : null;
}

function getFeatureEnergyClass(feature) {
  if (!feature || !feature.properties) return null;
  return normalizeEnergyClass(feature.properties.energy_class);
}

function normalizeCadastralCode(value) {
  if (value === null || value === undefined) return "";
  return String(value).trim().replace(/\s+/g, "").replace(/^0+/, "");
}

function stripDiacritics(value) {
  return String(value === null || value === undefined ? "" : value).normalize("NFD").replace(/[̀-ͯ]/g, "");
}

function normalizeSearchText(value) {
  return stripDiacritics(value).toUpperCase().replace(/\s+/g, " ").trim();
}

function getFeatureSearchLabel(feature) {
  const p = feature && feature.properties ? feature.properties : {};
  return p.building_title || p.ADDRESS || (p.CODE ? `Building ${p.CODE}` : "Building details");
}

function buildSearchIndex(features) {
  searchIndex = (Array.isArray(features) ? features : []).reduce((acc, feature, index) => {
    const p = feature && feature.properties ? feature.properties : null;
    if (!p) return acc;

    const rawCode = p.CODE ? String(p.CODE).trim().replace(/\s+/g, "") : "";
    const normalizedCode = rawCode ? normalizeCadastralCode(rawCode) : "";

    const rawAddress = p.ADDRESS ? String(p.ADDRESS).trim().replace(/\s+/g, " ") : "";
    const normalizedAddress = rawAddress ? normalizeSearchText(rawAddress) : "";

    if (!normalizedCode && !normalizedAddress) return acc;

    acc.push({
      feature: feature,
      rawCode: rawCode,
      normalizedCode: normalizedCode,
      rawAddress: rawAddress,
      normalizedAddress: normalizedAddress,
      label: getFeatureSearchLabel(feature),
      index: index
    });
    return acc;
  }, []);
}

function getSearchMatches(query, limit) {
  const normalizedCodeQuery = normalizeCadastralCode(query);
  const normalizedTextQuery = normalizeSearchText(query);
  if (!normalizedCodeQuery && !normalizedTextQuery) return [];

  const maxResults = typeof limit === "number" ? limit : 8;
  return searchIndex
    .filter(entry => {
      const codeMatch = !!normalizedCodeQuery && !!entry.normalizedCode && entry.normalizedCode.indexOf(normalizedCodeQuery) === 0;
      const addressMatch = !!normalizedTextQuery && !!entry.normalizedAddress && entry.normalizedAddress.indexOf(normalizedTextQuery) !== -1;
      return codeMatch || addressMatch;
    })
    .sort((a, b) => {
      const exactA = a.normalizedCode === normalizedCodeQuery ? 0 : 1;
      const exactB = b.normalizedCode === normalizedCodeQuery ? 0 : 1;
      if (exactA !== exactB) return exactA - exactB;
      if (a.normalizedCode.length !== b.normalizedCode.length) return a.normalizedCode.length - b.normalizedCode.length;
      return a.index - b.index;
    })
    .slice(0, maxResults);
}

function findRenderedLayerForFeature(feature) {
  if (!buildingsLayer || !feature) return null;
  var foundLayer = null;
  buildingsLayer.eachLayer(function (layer) {
    if (!foundLayer && layer && layer.feature === feature) {
      foundLayer = layer;
    }
  });
  return foundLayer;
}

function isNumericQuery(query) {
  const compact = String(query || "").replace(/\s+/g, "");
  return compact.length > 0 && /^[0-9]+$/.test(compact);
}

function renderSearchResults(query) {
  if (!searchResultsEl) return;

  const trimmedQuery = String(query || "").trim();
  const matches = getSearchMatches(trimmedQuery, 7);

  if (!trimmedQuery) {
    searchResultsEl.innerHTML = "";
    searchResultsEl.hidden = true;
    return;
  }

  if (!matches.length) {
    searchResultsEl.innerHTML = '<div class="search-empty">No matching building found.</div>';
    searchResultsEl.hidden = false;
    return;
  }

  const showCode = isNumericQuery(trimmedQuery);

  searchResultsEl.innerHTML = matches.map((entry, idx) => {
    const displayText = showCode ? (entry.rawCode || entry.rawAddress) : (entry.rawAddress || entry.rawCode);
    return `
      <button type="button" class="search-result-item" data-result-index="${idx}">
        <span class="search-result-code">${displayText}</span>
      </button>
    `;
  }).join("");
  searchResultsEl.hidden = false;

  searchResultsEl.querySelectorAll("[data-result-index]").forEach((button, idx) => {
    button.addEventListener("mousedown", function (event) {
      event.preventDefault();
    });
    button.addEventListener("click", function () {
      const selected = matches[idx];
      if (!selected) return;
      if (searchInputEl) searchInputEl.value = selected.rawCode;
      if (searchResultsEl) searchResultsEl.hidden = true;
      openSearchResult(selected.feature);
    });
  });
}

function openSearchResult(feature) {
  if (!feature || !feature.geometry) return;

  const bounds = L.geoJSON(feature).getBounds();
  if (!bounds.isValid()) return;

  const renderedLayer = findRenderedLayerForFeature(feature);
  let popupOpened = false;
  const openPopup = function () {
    if (popupOpened) return;
    popupOpened = true;

    if (renderedLayer && renderedLayer.getPopup()) {
      renderedLayer.openPopup();
      return;
    }

    L.popup({ maxWidth: 740, maxHeight: POPUP_MAX_HEIGHT, autoPan: true })
      .setLatLng(bounds.getCenter())
      .setContent(buildPopupContent(feature))
      .openOn(map);
  };

  map.once("moveend", openPopup);
  map.fitBounds(bounds, { padding: [60, 60], maxZoom: 19, animate: true });
  window.setTimeout(openPopup, 400);
}

function submitSearch() {
  if (!searchInputEl) return;

  const query = searchInputEl.value;
  const matches = getSearchMatches(query, 7);
  if (!matches.length) {
    renderSearchResults(query);
    return;
  }

  openSearchResult(matches[0].feature);
  if (searchResultsEl) {
    searchResultsEl.innerHTML = "";
    searchResultsEl.hidden = true;
  }
}

function setupSearchControl() {
  if (searchControl) return;

  searchControl = L.control({ position: "topleft" });
  searchControl.onAdd = function () {
    const div = L.DomUtil.create("div", "code-search-control leaflet-control");
    div.innerHTML = `
      <div class="code-search-panel">
        <div class="code-search-row">
          <input class="code-search-input" type="text" autocomplete="off" spellcheck="false" placeholder="Enter cadastral number or address" aria-label="Search by cadastral number or address">
          <button class="code-search-button" type="button" aria-label="Search for cadastral code">🔍︎</button>
        </div>
        <div class="code-search-results" hidden></div>
      </div>
    `;

    searchInputEl = div.querySelector(".code-search-input");
    const searchButtonEl = div.querySelector(".code-search-button");
    searchResultsEl = div.querySelector(".code-search-results");

    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);

    searchInputEl.addEventListener("input", function () {
      renderSearchResults(searchInputEl.value);
    });

    searchInputEl.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        submitSearch();
      }
      if (event.key === "Escape") {
        searchInputEl.value = "";
        renderSearchResults("");
      }
    });

    searchButtonEl.addEventListener("click", function () {
      submitSearch();
    });

    document.addEventListener("click", function (event) {
      if (div.contains(event.target)) return;
      searchInputEl.value = "";
      renderSearchResults("");
    });

    renderSearchResults("");
    return div;
  };

  searchControl.addTo(map);
}

/* ═══════════════════════════════════════════════════
   MAIN MAP
═══════════════════════════════════════════════════ */
var map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([56.9496, 24.1052], 15);
var geoJsonRenderer = L.canvas({ padding: 0.5 });

L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png', {
  attribution: '&copy; CARTO'
}).addTo(map);

/* ═══════════════════════════════════════════════════
   MINI MAP  
═══════════════════════════════════════════════════ */
var miniMap = L.map('minimap', {
  zoomControl:       false,
  attributionControl: false,
  dragging:          false,
  touchZoom:         false,
  doubleClickZoom:   false,
  scrollWheelZoom:   false,
  boxZoom:           false,
  keyboard:          false
}).setView([56.9496, 24.1052], 11);

L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png').addTo(miniMap);

/* ── Viewport rectangle overlay ── */
var viewportEl = document.getElementById('viewport-rect');
var miniWrapper = document.getElementById('minimap-wrapper');

function updateViewportRect() {
  var bounds = map.getBounds();
  var miniSize = miniMap.getSize();

  var nw = miniMap.latLngToContainerPoint(bounds.getNorthWest());
  var se = miniMap.latLngToContainerPoint(bounds.getSouthEast());

  var left   = Math.max(0, nw.x);
  var top    = Math.max(0, nw.y);
  var right  = Math.min(miniSize.x, se.x);
  var bottom = Math.min(miniSize.y, se.y);

  var w = Math.max(4, right - left);
  var h = Math.max(4, bottom - top);

  viewportEl.style.left   = left + 'px';
  viewportEl.style.top    = top  + 'px';
  viewportEl.style.width  = w    + 'px';
  viewportEl.style.height = h    + 'px';
}

/* Keep minimap centre & zoom in sync with main map */
function syncMiniMap() {
  var center = map.getCenter();
  var zoom   = Math.max(1, map.getZoom() - 5);
  miniMap.setView(center, zoom, { animate: false });
  updateViewportRect();
}

map.on('move',     syncMiniMap);
map.on('zoom',     syncMiniMap);
map.on('moveend',  updateViewportRect);
map.on('zoomend',  updateViewportRect);
miniMap.on('load', updateViewportRect);

/* ── Click / drag on minimap → pan main map ── */
var miniMapDragging = false;

function miniMapPointToMainLatLng(e) {
  var rect   = miniWrapper.getBoundingClientRect();
  var px     = e.clientX - rect.left;
  var py     = e.clientY - rect.top;
  return miniMap.containerPointToLatLng(L.point(px, py));
}

miniWrapper.addEventListener('mousedown', function (e) {
  if (e.target.closest('#minimap-home-btn')) return;
  miniMapDragging = true;
  map.panTo(miniMapPointToMainLatLng(e), { animate: true, duration: 0.25 });
  e.preventDefault();
});

document.addEventListener('mousemove', function (e) {
  if (!miniMapDragging) return;
  map.panTo(miniMapPointToMainLatLng(e), { animate: false });
});

document.addEventListener('mouseup', function () {
  miniMapDragging = false;
});

/* Touch support */
miniWrapper.addEventListener('touchstart', function (e) {
  if (e.target.closest('#minimap-home-btn')) return;
  miniMapDragging = true;
  var t = e.touches[0];
  map.panTo(miniMapPointToMainLatLng(t), { animate: true, duration: 0.25 });
  e.preventDefault();
}, { passive: false });

document.addEventListener('touchmove', function (e) {
  if (!miniMapDragging) return;
  var t = e.touches[0];
  map.panTo(miniMapPointToMainLatLng(t), { animate: false });
});

document.addEventListener('touchend', function () {
  miniMapDragging = false;
});

/* ── Toggle button ── */
var minimapVisible = true;
var toggleBtn = document.getElementById('minimap-toggle');

toggleBtn.addEventListener('click', function () {
  minimapVisible = !minimapVisible;
  miniWrapper.style.display = minimapVisible ? '' : 'none';
  toggleBtn.style.bottom    = minimapVisible ? '178px' : '20px';
  toggleBtn.style.borderRadius = minimapVisible ? '6px 6px 0 0' : '6px';
  toggleBtn.style.borderBottom = minimapVisible ? 'none' : '1px solid rgba(0,0,0,0.18)';
  toggleBtn.textContent = minimapVisible ? '▼' : '▲';
  updateCityOverviewAnchor();
});

/* ── Left-side panel accordion ─────────────────────────────────────
   Region Filter, Meteorological stations and Air quality stations share
   the same strip of screen space down the left edge, so at most one of
   the three is ever open — opening one collapses whichever of the other
   two was open. Each starts collapsed. The minimap keeps its own
   independent ▼/▲ toggle above and isn't part of this group. */
var accordionPanels = [];

function collapseAccordionPanel(panel) {
  panel.el.classList.add("collapsed");
  panel.btn.textContent = "▸";
  panel.btn.setAttribute("aria-label", panel.expandLabel);
}

function expandAccordionPanel(panel) {
  accordionPanels.forEach(function (p) { if (p !== panel) collapseAccordionPanel(p); });
  panel.el.classList.remove("collapsed");
  panel.btn.textContent = "▾";
  panel.btn.setAttribute("aria-label", panel.collapseLabel);
}

function registerAccordionPanel(el, btn, collapseLabel, expandLabel) {
  var panel = { el: el, btn: btn, collapseLabel: collapseLabel, expandLabel: expandLabel };
  accordionPanels.push(panel);
  collapseAccordionPanel(panel);
  btn.addEventListener("click", function () {
    if (panel.el.classList.contains("collapsed")) expandAccordionPanel(panel);
    else collapseAccordionPanel(panel);
  });
  return panel;
}

/* Keeps a filter-chip's active/aria-expanded state in sync when its panel is
   collapsed via the panel's own internal button rather than via the chip
   itself (chip clicks already do this through setPanelCollapsed's caller). */
function syncChipActiveState(chipKey, collapsed) {
  var chipBtn = document.querySelector('.filter-chip[data-chip="' + chipKey + '"]');
  if (!chipBtn) return;
  var isActive = !collapsed;
  chipBtn.classList.toggle("active", isActive);
  chipBtn.setAttribute("aria-expanded", String(isActive));
}

document.querySelectorAll(".aq-station-card").forEach(card => {
  const btn = card.querySelector("[data-collapse-toggle]");
  const title = card.querySelector(".aq-station-card-title").textContent;
  if (btn) registerAccordionPanel(card, btn, "Collapse " + title.toLowerCase(), "Expand " + title.toLowerCase());
});

/* ── "Return to Riga" button ── */
var RIGA_HOME_CENTER = [56.9496, 24.1052];
var RIGA_HOME_ZOOM = 15;
var homeBounds = null;
var homeBtn = document.getElementById('minimap-home-btn');

homeBtn.addEventListener('click', function (e) {
  e.stopPropagation();
  map.closePopup();
  if (homeBounds && homeBounds.isValid()) {
    map.flyToBounds(homeBounds, { animate: true, duration: 0.8 });
  } else {
    map.flyTo(RIGA_HOME_CENTER, RIGA_HOME_ZOOM, { animate: true, duration: 0.8 });
  }
});

/* ═══════════════════════════════════════════════════
   COLOUR HELPERS
═══════════════════════════════════════════════════ */
function getEnergyColor(energyClass) {
  switch (energyClass) {
    case "A+": return "#0F6C3A";
    case "A": return "#1B5E20";
    case "B": return "#7CB342";
    case "C": return "#FDD835";
    case "D": return "#FB8C00";
    case "E": return "#E53935";
    case "F": return "#8E0000";
    default:  return "#BDBDBD";
  }
}

function style(feature) {
  const energyClass = getFeatureEnergyClass(feature) || "F";
  return {
    fillColor: getEnergyColor(energyClass),
    weight: 1,
    color: 'black',
    fillOpacity: 0.7
  };
}

/* Drives both bar instances at once (cheap — a few DOM writes either
   way): the Energy Class panel's own bar (#legend-bar / #legend-bar-count)
   and the compact bottom-sheet's (#bottom-sheet-bar / #bottom-sheet-count)
   — same bar markup/style (.bottom-sheet-bar / .bottom-sheet-count),
   just two separate instances of it. */
function updateStatsPanel() {
  var legendBarEl = document.getElementById("legend-bar");
  var legendBarCountEl = document.getElementById("legend-bar-count");
  var barEl = document.getElementById("bottom-sheet-bar");
  var countEl = document.getElementById("bottom-sheet-count");
  if (!legendBarEl && !barEl) return;

  const counts = {};
  CLASS_ORDER.forEach(c => counts[c] = 0);
  let total = 0;

  if (buildingsLayer) {
    const viewport = map.getBounds();
    buildingsLayer.eachLayer(function (lyr) {
      const cls = getFeatureEnergyClass(lyr.feature);
      if (!cls || !counts.hasOwnProperty(cls)) return;

      let visible = false;
      if (typeof lyr.getBounds === "function") visible = viewport.intersects(lyr.getBounds());
      else if (typeof lyr.getLatLng === "function") visible = viewport.contains(lyr.getLatLng());

      if (!visible) return;
      counts[cls] += 1;
      total += 1;
    });
  }

  function renderBar(countTargetEl, barTargetEl) {
    if (!countTargetEl || !barTargetEl) return;
    countTargetEl.textContent = total ? `${total} building${total === 1 ? "" : "s"} in view` : "No buildings in view";
    barTargetEl.innerHTML = CLASS_ORDER
      .filter(cls => counts[cls] > 0)
      .map(cls => `<span style="flex:${counts[cls]} 0 0;background:${getEnergyColor(cls)};" title="${cls}: ${counts[cls]}"></span>`)
      .join("");
  }

  renderBar(legendBarCountEl, legendBarEl);
  renderBar(countEl, barEl);
}

/* ═══════════════════════════════════════════════════
   HIGHLIGHT / RESET
═══════════════════════════════════════════════════ */
function highlightFeature(e) {
  e.target.setStyle({ weight: 4, color: "#000", fillOpacity: 0.9 });
  if (!L.Browser.ie && !L.Browser.opera && !L.Browser.edge) e.target.bringToFront();
}

function resetHighlight(e) {
  e.target.setStyle({ weight: 2, color: "black", fillOpacity: 0.7 });
}

/* ═══════════════════════════════════════════════════
   HEATING CHART HELPERS
═══════════════════════════════════════════════════ */
function parseNum(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "number") return v;
  const n = Number(String(v).replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function fmtMWh(v) {
  const n = parseNum(v);
  return (n === null) ? "-" : n.toFixed(2);
}

function escapeForAttr(str) {
  return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function downloadJSON(filename, dataObj) {
  const blob = new Blob([JSON.stringify(dataObj, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportBuildingData(btn) {
  const raw = btn.getAttribute("data-export");
  if (!raw) return;
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    console.error("[map] Failed to parse export payload", e);
    return;
  }
  const safeCode = String(payload.cadastral_number || "building").replace(/[^a-zA-Z0-9_-]+/g, "_");
  downloadJSON(`building-${safeCode}.json`, payload);
}

function parseHeatingIndicator(v) {
  if (v === null || v === undefined || String(v).trim() === "") return null;
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return null;
    return Math.abs(v) <= 1 ? v * 100 : v;
  }

  const cleaned = String(v).replace("%", "").replace(",", ".").trim();
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function fmtPct(v) {
  if (v === null) return "-";
  const rounded = Math.round(v * 10) / 10;
  const sign = rounded > 0 ? "+" : "";
  return `${sign}${rounded.toFixed(1)}%`;
}

/* Shared by the building popup's "comparison with similar buildings" meter
   and the city overview filter's slider version of the same control, so
   both always render identically off the same math. */
function computeIndicatorVisual(v) {
  const indicatorClass = v === null ? "neutral" : (v > 0 ? "over" : (v < 0 ? "under" : "neutral"));
  const indicatorWidth = v === null ? 0 : Math.min(50, Math.abs(v) * 0.5);
  const indicatorPointPos = v === null ? 50 : Math.max(0, Math.min(100, 50 + (v * 0.5)));
  const indicatorEdgeClass = indicatorPointPos >= 92 ? "edge-right" : (indicatorPointPos <= 8 ? "edge-left" : "");
  const indicatorValueText = fmtPct(v);
  return { indicatorClass, indicatorWidth, indicatorPointPos, indicatorEdgeClass, indicatorValueText };
}

function formatMonthYear(value) {
  const raw = String(value || "").trim();
  let mm = null, yyyy = null;

  let match = raw.match(/^(\d{1,2})\.(\d{4})$/);
  if (match) {
    mm = parseInt(match[1], 10);
    yyyy = match[2];
  } else {
    match = raw.match(/^(\d{4})-(\d{1,2})$/);
    if (match) {
      yyyy = match[1];
      mm = parseInt(match[2], 10);
    }
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const MONTHS_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  if (mm && mm >= 1 && mm <= 12 && yyyy) return `${MONTHS_FULL[mm - 1]} ${yyyy}`;
  return raw || "-";
}

function lineChartSVG(months, values) {
  const nums = values.map(v => parseNum(v)).map(v => v ?? 0);

  const w = 328, h = 144;
  const pad = { l: 36, r: 18, t: 14, b: 32 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const maxV = Math.max(...nums, 1);
  const stepX = nums.length > 1 ? plotW / (nums.length - 1) : plotW;

  function niceMax(v) {
    if (v <= 0) return 1;
    const exp = Math.floor(Math.log10(v));
    const f = v / Math.pow(10, exp);
    if (f <= 1) return 1 * Math.pow(10, exp);
    if (f <= 2) return 2 * Math.pow(10, exp);
    if (f <= 5) return 5 * Math.pow(10, exp);
    return 10 * Math.pow(10, exp);
  }

  const yMax = niceMax(maxV);
  const x = i => pad.l + i * stepX;
  const y = v => pad.t + plotH - (v / yMax) * plotH;
  const last = nums.length - 1;
  const prev = last - 1;
  const latestDotColor = "#176087";
  const previousDotColor = "#1f5ed8";
  const defaultDotColor = "#5e95f5";

  const points = nums.map((v, i) => ({ x: x(i), y: y(v), v, i }));

  function pointAt(idx) {
    if (idx < 0) return points[0];
    if (idx >= points.length) return points[points.length - 1];
    return points[idx];
  }

  function getSegmentBezier(i) {
    const p0 = pointAt(i - 1);
    const p1 = pointAt(i);
    const p2 = pointAt(i + 1);
    const p3 = pointAt(i + 2);
    const tension = 1;
    const cp1x = p1.x + ((p2.x - p0.x) / 6) * tension;
    const cp1y = p1.y + ((p2.y - p0.y) / 6) * tension;
    const cp2x = p2.x - ((p3.x - p1.x) / 6) * tension;
    const cp2y = p2.y - ((p3.y - p1.y) / 6) * tension;
    return { cp1x, cp1y, cp2x, cp2y, p1, p2 };
  }

  let smoothPath = "";
  if (points.length > 0) {
    smoothPath = `M ${points[0].x} ${points[0].y} `;
    for (let i = 0; i < points.length - 1; i++) {
      const seg = getSegmentBezier(i);
      smoothPath += `C ${seg.cp1x} ${seg.cp1y}, ${seg.cp2x} ${seg.cp2y}, ${seg.p2.x} ${seg.p2.y} `;
    }
  }

  const areaPath = points.length > 0
    ? `${smoothPath} L ${points[points.length - 1].x} ${h - pad.b} L ${points[0].x} ${h - pad.b} Z`
    : "";

  function monthNum(raw) {
    const str = String(raw || "").trim();
    let match = str.match(/^(\d{4})-(\d{1,2})$/);
    if (match) return parseInt(match[2], 10);
    match = str.match(/^(\d{1,2})\.(\d{4})$/);
    if (match) return parseInt(match[1], 10);
    return null;
  }

  function seasonColor(mm) {
    if (mm === null) return "#5e95f5";
    if ([11, 12, 1, 2, 3].includes(mm)) return "#2463db";
    if ([4, 5, 9, 10].includes(mm)) return "#3d8b55";
    return "#b5beca";
  }

  let seasonalSegments = "";
  for (let i = 0; i < points.length - 1; i++) {
    const seg = getSegmentBezier(i);
    const mm = monthNum(months[i + 1]);
    const clr = seasonColor(mm);
    seasonalSegments += `<path d="M ${seg.p1.x} ${seg.p1.y} C ${seg.cp1x} ${seg.cp1y}, ${seg.cp2x} ${seg.cp2y}, ${seg.p2.x} ${seg.p2.y}" fill="none" stroke="${clr}" stroke-width="2.25" stroke-linecap="round"/>`;
  }

  const ticks = 4;
  let yTicks = "";
  for (let i = 0; i <= ticks; i++) {
    const val = (yMax / ticks) * i;
    const yy = y(val);
    yTicks += `
      <line x1="${pad.l}" y1="${yy}" x2="${w - pad.r}" y2="${yy}" stroke="#dde5ef" stroke-dasharray="3,3"/>
      <text x="${pad.l - 8}" y="${yy + 4}" font-size="10" fill="#5f6b7a" text-anchor="end">${Math.round(val)}</text>
    `;
  }

  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  let xTicks = "";
  months.forEach((m, i) => {
    const mm = monthNum(m);
    const label = MONTHS[mm - 1] || "";
    xTicks += `<text x="${x(i)}" y="${h - 9}" font-size="10" fill="#5f6b7a" text-anchor="middle">${label}</text>`;
  });

  let pointMarkup = "";
  nums.forEach((v, i) => {
    const isLatest = i === last;
    const isPrevious = i === prev;
    const r = isLatest ? 5.5 : (isPrevious ? 4.8 : 3.7);
    const fill = isLatest ? latestDotColor : (isPrevious ? previousDotColor : defaultDotColor);
    const stroke = "#ffffff";

    // Keep the hover tooltip inside the chart canvas: flip it below the dot
    // when there isn't room above (high values near the top get clipped
    // otherwise), and clamp it sideways so the first/last month's tooltip
    // doesn't run off the left/right edge.
    let tipRectY = y(v) - 30;
    if (tipRectY < 2) tipRectY = y(v) + 14;
    if (tipRectY > h - 18) tipRectY = h - 18;
    const tipTextY = tipRectY + 11;
    let tipCx = x(i);
    if (tipCx - 35 < 2) tipCx = 35 + 2;
    if (tipCx + 35 > w - 2) tipCx = w - 2 - 35;

    pointMarkup += `
      <g class="dot-group" style="pointer-events:all;cursor:default;">
        <circle cx="${x(i)}" cy="${y(v)}" r="8" fill="transparent"/>
        <circle class="chart-dot" cx="${x(i)}" cy="${y(v)}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="1.2">
          <title>${months[i]} - ${v.toFixed(2)} MWh</title>
        </circle>
        <g class="chart-tip">
          <rect x="${tipCx - 35}" y="${tipRectY}" width="70" height="16" rx="5" ry="5" fill="rgba(17,24,39,0.92)"/>
          <text x="${tipCx}" y="${tipTextY}" font-size="9.8" fill="#ffffff" text-anchor="middle">${v.toFixed(2)} MWh</text>
        </g>
      </g>
    `;
  });

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block;pointer-events:auto;">
      <style>
        .dot-group .chart-tip { opacity: 0; pointer-events: none; transition: opacity 0.15s ease; }
        .dot-group .chart-dot { opacity: 0; transition: opacity 0.15s ease; }
        .dot-group:hover .chart-tip,
        .dot-group:hover .chart-dot { opacity: 1; }
      </style>
      <defs>
        <linearGradient id="chartAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(31,94,216,0.26)"/>
          <stop offset="68%" stop-color="rgba(31,94,216,0.10)"/>
          <stop offset="100%" stop-color="rgba(31,94,216,0.01)"/>
        </linearGradient>
      </defs>
      <rect x="0" y="0" width="${w}" height="${h}" rx="10" ry="10" fill="#fdfefe"/>
      ${yTicks}
      <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${h - pad.b}" stroke="#8d98a8"/>
      <line x1="${pad.l}" y1="${h - pad.b}" x2="${w - pad.r}" y2="${h - pad.b}" stroke="#8d98a8"/>
      <path d="${areaPath}" fill="url(#chartAreaGrad)"/>
      ${seasonalSegments}
      ${pointMarkup}
      ${xTicks}
    </svg>
  `;
}

function bd(p, key) {
  return p?.building_data?.[0]?.[key] ?? "-";
}

// Shared by the single-building popup export and the city-scale overview's
// bulk export, so both produce buildings in the exact same shape.
function buildBuildingExportPayload(feature) {
  const p = feature.properties || {};
  const tsEntries = Object.entries(p.heat_consumption_timeseries || {})
    .filter(([k]) => /^\d{4}-\d{2}$/.test(String(k)))
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  const detailPairs = [
    ["Ground floors", bd(p, "BuildingBasicData.BuildingGroundFloors")],
    ["Underground floors", bd(p, "BuildingBasicData.BuildingUndergroundFloors")],
    ["Apartments", bd(p, "BuildingBasicData.BuildingPregCount")],
    ["Total area", (() => { const val = bd(p, "BuildingOrPremiseGroupExplicationData.TotalArea"); return val && val !== "-" ? `${val} m²` : val; })()],
    ["Useful area", (() => { const val = bd(p, "BuildingOrPremiseGroupExplicationData.TotalAreaDetails.ExpedientArea"); return val && val !== "-" ? `${val} m²` : val; })()],
    ["Reference (heated) area", p.reference_area_m2 ? `${Number(p.reference_area_m2).toFixed(1)} m²` : "-"],
    ["Construction year", p.manufacture_year || "-"],
    ["Renovation year", p.renovation || "-"],
    ["Construction materials", p.heavy_light ? p.heavy_light.charAt(0).toUpperCase() + p.heavy_light.slice(1) : "Not specified"]
  ];
  return {
    cadastral_number: p.CODE || null,
    address: p.ADDRESS || null,
    energy_class: getFeatureEnergyClass(feature) || "-",
    building_details: Object.fromEntries(detailPairs),
    heat_consumption_mwh_by_month: Object.fromEntries(tsEntries.map(([k, v]) => [k, parseNum(v)]))
  };
}

/* ═══════════════════════════════════════════════════
   POPUP
═══════════════════════════════════════════════════ */
function buildPopupContent(feature) {
  const p = feature.properties || {};
  const tsEntries = Object.entries(p.heat_consumption_timeseries || {})
    .filter(([k]) => /^\d{4}-\d{2}$/.test(String(k)))
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  const last12Entries = tsEntries.slice(-12);
  const months = last12Entries.map(([k]) => String(k));
  const vals = last12Entries.map(([, v]) => parseNum(v));

  const latestEntry = tsEntries.length ? tsEntries[tsEntries.length - 1] : null;
  const previousEntry = tsEntries.length > 1 ? tsEntries[tsEntries.length - 2] : null;
  const latestMonthRaw = latestEntry ? latestEntry[0] : "-";
  const prevMonthRaw = previousEntry ? previousEntry[0] : "-";
  const latestVal = latestEntry ? parseNum(latestEntry[1]) : null;
  const prevVal = previousEntry ? parseNum(previousEntry[1]) : null;
  const latestMonth = formatMonthYear(latestMonthRaw);
  const prevMonth = formatMonthYear(prevMonthRaw);

  let pct = null;
  if (prevVal !== null && prevVal !== 0 && latestVal !== null)
    pct = ((latestVal - prevVal) / prevVal) * 100;

  const cls = getFeatureEnergyClass(feature) || "-";
  const buildingTitle = p.building_title || p.address || (p.CODE ? `Building ${p.CODE}` : "Building details");
  const energyColor = getEnergyColor(cls);

  const changeText  = pct === null ? "-" : (pct > 0 ? `+${pct.toFixed(1)}%` : `${pct.toFixed(1)}%`);
  const changeArrow = pct === null ? "" : (pct > 0 ? "▲" : (pct < 0 ? "▼" : "■"));
  const changeClass = pct === null ? "neutral" : (pct > 0 ? "warn" : (pct < 0 ? "good" : "neutral"));

  const chartHTML   = vals.length ? lineChartSVG(months, vals) : "";
  const annualUsagePerArea = computeAnnualStats(p).perArea;
  const annualUsagePerAreaText = annualUsagePerArea !== null ? `${annualUsagePerArea.toFixed(0)} kWh/m²` : "-";
  const annualRangeText = months.length ? `${formatMonthYear(months[0])} - ${formatMonthYear(months[months.length - 1])}` : "-";
  const apiUrl = p.api_url || p.open_api_url || p.api || "";
  const safeApiUrl = String(apiUrl).replace(/'/g, "%27");
  const heatIndicator = parseHeatingIndicator(p.heating_indicator);
  const { indicatorClass, indicatorWidth, indicatorPointPos, indicatorEdgeClass, indicatorValueText } = computeIndicatorVisual(heatIndicator);

  const detailPairs = [
    ["Ground floors", bd(p, "BuildingBasicData.BuildingGroundFloors")],
    ["Underground floors", bd(p, "BuildingBasicData.BuildingUndergroundFloors")],
    ["Apartments", bd(p, "BuildingBasicData.BuildingPregCount")],
    ["Total area", (() => { const val = bd(p, "BuildingOrPremiseGroupExplicationData.TotalArea"); return val && val !== "-" ? `${val} m²` : val; })()],
    ["Useful area", (() => { const val = bd(p, "BuildingOrPremiseGroupExplicationData.TotalAreaDetails.ExpedientArea"); return val && val !== "-" ? `${val} m²` : val; })()],
    ["Reference (heated) area", p.reference_area_m2 ? `${Number(p.reference_area_m2).toFixed(1)} m²` : "-"],
    ["Construction year", p.manufacture_year || "-"],
    ["Renovation year", p.renovation || "-"],
    ["Construction materials", p.heavy_light ? p.heavy_light.charAt(0).toUpperCase() + p.heavy_light.slice(1) : "Not specified"]
  ];

  const detailRows = detailPairs.map(([label, value]) => `
    <div class="fact-row">
      <div class="fact-label">${label}</div>
      <div class="fact-value">${value ?? "-"}</div>
    </div>
  `).join("");

  const safeExportPayload = escapeForAttr(JSON.stringify(buildBuildingExportPayload(feature)));

  return `
    <div class="building-popup">
      <div class="building-popup-header">
        <div>
          <div class="title-line">
          <h3 class="building-title">Building profile</h3>
          <span class="energy-badge" style="background:${energyColor};">Class ${cls}</span>
          </div>
          <div class="building-subtitle">Cadastral number: ${p.CODE || "-"}</div>
          <div class="building-subtitle">Address: ${p.ADDRESS || "-"}</div>
        </div>
      </div>

      <div class="building-popup-grid">
        <div class="details-col">
          <h4 class="section-title details-title">Building details</h4>
          <div class="panel-card details-card">
            ${detailRows}
          </div>
          <div class="panel-card indicator-card ${indicatorClass}">
            <div class="indicator-head">
              <div class="indicator-title">Comparison with similar buildings</div>
              <button type="button" class="indicator-help-btn" aria-label="Explain comparison indicator" onclick="event.stopPropagation(); this.closest('.indicator-card').classList.toggle('show-help');">?</button>
              <div class="indicator-help">
                This value shows how the building's heating consumption compares to the average of similar buildings (i.e. those with approximately same area and period of construction).<br>
                - +15% -> your building uses 15% more heat energy than similar buildings<br>
                - -20% -> your building uses 20% less heat energy than similar buildings<br>
                - 0% -> your building is right at the average
              </div>
            </div>
            <div class="indicator-meter" aria-hidden="true">
              <div class="indicator-track">
                <div class="indicator-mid"></div>
                <div class="indicator-fill ${indicatorClass}" style="width:${indicatorWidth}%;"></div>
              </div>
              <div class="indicator-point-wrap ${indicatorEdgeClass}" style="left:${indicatorPointPos}%;">
                <div class="indicator-value-chip ${indicatorClass}">${indicatorValueText}</div>
                <div class="indicator-point ${indicatorClass}"></div>
              </div>
            </div>
            <div class="indicator-scale">
              <span>Lower</span>
              <span>Higher</span>
            </div>
          </div>
        </div>

        <div class="right-col">
          <h4 class="kpi-title">Heat consumption summary</h4>
          <div class="kpi-grid">
            <div class="kpi-card latest-card">
              <div class="kpi-label">Latest month</div>
              <div class="kpi-value latest">${fmtMWh(latestVal)} MWh</div>
              <div class="kpi-sub">${latestMonth}</div>
            </div>

            <div class="kpi-card previous-card">
              <div class="kpi-label">Previous month</div>
              <div class="kpi-value previous">${fmtMWh(prevVal)} MWh</div>
              <div class="kpi-sub">${prevMonth}</div>
            </div>

            <div class="kpi-card change-card ${changeClass}">
              <div class="kpi-label">Monthly change</div>
              <div class="kpi-change ${changeClass}">${changeArrow} ${changeText}</div>
              <div class="kpi-sub">Current month compared with previous month</div>
            </div>
          </div>

          <div class="chart-card">
            <h4 class="chart-title">Monthly Heat Consumption (MWh)</h4>
            <div class="chart-wrap">
              ${chartHTML || '<div class="kpi-sub" style="padding:10px;text-align:center;">No 12-month data available</div>'}
            </div>
          </div>

          <div class="kpi-card annual-usage-card">
            <div class="kpi-label">Last year's heat consumption per area</div>
            <div class="kpi-value latest">${annualUsagePerAreaText}</div>
            <div class="kpi-sub">${annualRangeText}</div>
          </div>
        </div>
      </div>

      <div class="popup-actions">
        <button class="api-btn" ${apiUrl ? `onclick="window.open('${safeApiUrl}','_blank')"` : "disabled"}>Open API</button>
        <button type="button" class="export-btn" data-export="${safeExportPayload}" onclick="exportBuildingData(this);">Export data</button>
      </div>
    </div>
  `;
}

/* Leaflet's default autoPan (which shifts the map so a newly-opened or
   re-anchored popup stays fully visible) only keeps 5px clear from the
   map's own edges — it has no idea our custom overlays (zoom control,
   search bar, filter chips up top; bottom sheet, minimap, station cards
   down low) are sitting on top of that space. Without this padding, a
   popup can autoPan to a position that's on-map but visually behind our
   own UI, which shows up as "the popup gets cut off" after zooming (the
   popup re-anchors to its feature, autoPan kicks in again, and it lands
   in that dead zone).
   Popups can never actually stack above these overlays via z-index, no
   matter how high: Leaflet pans the whole map by transform-ing
   .leaflet-map-pane, which creates its own stacking context with no
   z-index of its own, so it — and everything inside it, popups included
   — paints as a single unit below any sibling that has an explicit
   z-index (.bottom-sheet, .filter-chips, etc. all do). Padding that
   actually keeps autoPan from landing a popup under them is the only
   real fix.
   Bottom padding must clear the tallest thing sitting on the bottom
   edge — the minimap + .city-overview-toggle-btn stack, bottom-right
   (bottom:210px + the button's own ~38px height, see styles.css). On a
   short browser window there just isn't much room left over for a tall
   popup to avoid scrolling internally — that's an inherent trade-off of
   keeping this much fixed UI on screen, not a bug. */
var POPUP_AUTOPAN_PADDING = { autoPanPaddingTopLeft: L.point(20, 140), autoPanPaddingBottomRight: L.point(20, 260) };

/* Popup content (building details + charts) can be taller than the map
   itself now that #map-viewport no longer claims a full 100vh (see
   styles.css) — without an explicit maxHeight, Leaflet lets the popup
   grow past the bottom of the map instead of scrolling internally.
   Sized against the same padding autoPan already leaves clear above/
   below, so the popup never claims space we know is covered by our own
   UI. */
var POPUP_MAX_HEIGHT = Math.max(280, map.getSize().y - POPUP_AUTOPAN_PADDING.autoPanPaddingTopLeft.y - POPUP_AUTOPAN_PADDING.autoPanPaddingBottomRight.y);

function onEachFeature(feature, layer) {
  layer.on({ mouseover: highlightFeature, mouseout: resetHighlight });
  layer.bindPopup(function () {
    return buildPopupContent(feature);
  }, Object.assign({ maxWidth: 740, maxHeight: POPUP_MAX_HEIGHT }, POPUP_AUTOPAN_PADDING));
}

/* ═══════════════════════════════════════════════════
   REGION BOUNDARIES (Riga suburbs, LKS-92 → WGS84)
═══════════════════════════════════════════════════ */
var LKS92_A = 6378137;
var LKS92_F = 1 / 298.257222101;
var LKS92_K0 = 0.9996;
var LKS92_LON0 = 24 * Math.PI / 180;
var LKS92_FE = 500000;
var LKS92_FN = -6000000;

function lks92ToWgs84(easting, northing) {
  const e2 = LKS92_F * (2 - LKS92_F);
  const e4 = e2 * e2, e6 = e4 * e2;
  const ep2 = e2 / (1 - e2);
  const x = easting - LKS92_FE;
  const y = northing - LKS92_FN;
  const M = y / LKS92_K0;
  const mu = M / (LKS92_A * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256));
  const e1 = (1 - Math.sqrt(1 - e2)) / (1 + Math.sqrt(1 - e2));
  const J1 = 3 * e1 / 2 - 27 * e1 * e1 * e1 / 32;
  const J2 = 21 * e1 * e1 / 16 - 55 * e1 * e1 * e1 * e1 / 32;
  const J3 = 151 * e1 * e1 * e1 / 96;
  const J4 = 1097 * e1 * e1 * e1 * e1 / 512;
  const fp = mu + J1 * Math.sin(2 * mu) + J2 * Math.sin(4 * mu) + J3 * Math.sin(6 * mu) + J4 * Math.sin(8 * mu);
  const C1 = ep2 * Math.cos(fp) * Math.cos(fp);
  const T1 = Math.tan(fp) * Math.tan(fp);
  const N1 = LKS92_A / Math.sqrt(1 - e2 * Math.sin(fp) * Math.sin(fp));
  const R1 = LKS92_A * (1 - e2) / Math.pow(1 - e2 * Math.sin(fp) * Math.sin(fp), 1.5);
  const D = x / (N1 * LKS92_K0);

  const lat = fp - (N1 * Math.tan(fp) / R1) * (
    D * D / 2
    - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * ep2) * D * D * D * D / 24
    + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * ep2 - 3 * C1 * C1) * D * D * D * D * D * D / 720
  );
  const lon = LKS92_LON0 + (
    D
    - (1 + 2 * T1 + C1) * D * D * D / 6
    + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * ep2 + 24 * T1 * T1) * D * D * D * D * D / 120
  ) / Math.cos(fp);

  return [lon * 180 / Math.PI, lat * 180 / Math.PI];
}

function parseRegionsCsv(text) {
  const lines = String(text || "").split(/\r?\n/).filter(l => l.trim().length);
  const regions = [];

  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    const firstSemi = line.indexOf(";");
    const secondSemi = line.indexOf(";", firstSemi + 1);
    if (firstSemi === -1 || secondSemi === -1) continue;

    const name = line.slice(firstSemi + 1, secondSemi).trim();
    const wkt = line.slice(secondSemi + 1).trim();
    const open = wkt.indexOf("((");
    const close = wkt.lastIndexOf("))");
    if (!name || open === -1 || close === -1) continue;

    const ring = wkt.slice(open + 2, close).split(",").map(pair => {
      const parts = pair.trim().split(/\s+/);
      return lks92ToWgs84(parseFloat(parts[0]), parseFloat(parts[1]));
    });
    if (!ring.length) continue;

    let sumLon = 0, sumLat = 0;
    ring.forEach(pt => { sumLon += pt[0]; sumLat += pt[1]; });

    regions.push({ name, ring, centroid: [sumLon / ring.length, sumLat / ring.length] });
  }

  return regions;
}

function pointInRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect = ((yi > lat) !== (yj > lat)) &&
      (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function getFeatureCentroid(feature) {
  const ring = feature && feature.geometry && feature.geometry.coordinates && feature.geometry.coordinates[0];
  if (!ring || !ring.length) return null;
  let sumLon = 0, sumLat = 0;
  for (let i = 0; i < ring.length; i++) {
    sumLon += ring[i][0];
    sumLat += ring[i][1];
  }
  return [sumLon / ring.length, sumLat / ring.length];
}

function assignFeatureRegions(features) {
  if (!regionPolygons.length) return;
  (Array.isArray(features) ? features : []).forEach(feature => {
    if (!feature || !feature.properties) return;
    const centroid = getFeatureCentroid(feature);
    if (!centroid) return;

    let matched = null;
    for (let i = 0; i < regionPolygons.length; i++) {
      if (pointInRing(centroid[0], centroid[1], regionPolygons[i].ring)) {
        matched = regionPolygons[i].name;
        break;
      }
    }

    if (!matched) {
      let bestName = null, bestDist = Infinity;
      regionPolygons.forEach(region => {
        const dLon = region.centroid[0] - centroid[0];
        const dLat = region.centroid[1] - centroid[1];
        const dist = dLon * dLon + dLat * dLat;
        if (dist < bestDist) { bestDist = dist; bestName = region.name; }
      });
      matched = bestName;
    }

    feature.properties.__region = matched;
  });
}

/* ═══════════════════════════════════════════════════
   AIR QUALITY MONITORING STATIONS
═══════════════════════════════════════════════════ */
var AQ_FILES = [
  DATA_BASE_URL + "ikmnea-gaisa-dati-2025.07-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2025.08-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2025.09-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2025.10-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2025.11-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2025.12-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2026.01-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2026.02-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2026.03-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2026.04-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2026.05-daily.json",
  DATA_BASE_URL + "ikmnea-gaisa-dati-2026.06-daily.json"
];

var AQ_LEVELS = ["Good", "Fair", "Moderate", "Poor", "Very Poor"];
var AQ_LEVEL_COLORS = {
  "Good": "rgba(111,168,232,0.85)",
  "Fair": "rgba(120,198,126,0.85)",
  "Moderate": "rgba(233,161,58,0.85)",
  "Poor": "rgba(213,97,92,0.85)",
  "Very Poor": "rgba(195,154,236,0.85)"
};
var AQ_FALLBACK_COLOR = "#c3cbd6";
var AQ_POLLUTANTS = ["PM2.5", "PM10", "NO2", "SO2", "O3"];
var AQ_POLLUTANT_BAR_COLOR = "rgba(180,187,196,0.85)";

// 1-hour average thresholds (µg/m³) each level is defined by, mirroring
// classify_air_quality.py's THRESHOLDS table exactly — shown to users via
// the popup's help button so the levels/colors aren't a black box.
var AQ_LEVEL_THRESHOLDS = {
  "Good":      { "PM2.5": "0–5",   "PM10": "0–15",   "NO2": "0–10",   "SO2": "0–20",   "O3": "0–60" },
  "Fair":      { "PM2.5": "6–15",  "PM10": "16–45",  "NO2": "11–25",  "SO2": "21–40",  "O3": "61–100" },
  "Moderate":  { "PM2.5": "16–50", "PM10": "46–120", "NO2": "26–60",  "SO2": "41–125", "O3": "101–120" },
  "Poor":      { "PM2.5": "51–90", "PM10": "121–195","NO2": "61–100", "SO2": "126–190","O3": "121–160" },
  "Very Poor": { "PM2.5": "91–140","PM10": "196–270","NO2": "101–150","SO2": "191–275","O3": "161–180" }
};

function aqLevelsHelpInnerHTML() {
  const rows = AQ_LEVELS.map(lvl => `
    <tr>
      <td>
        <span class="aq-levels-help-level">
          <span class="aq-legend-swatch" style="background:${AQ_LEVEL_COLORS[lvl]}"></span>
          ${lvl}
        </span>
      </td>
      ${AQ_POLLUTANTS.map(p => `<td>${AQ_LEVEL_THRESHOLDS[lvl][p]}</td>`).join("")}
    </tr>
  `).join("");

  return `
    <table class="legend-table aq-levels-help-table">
      <thead>
        <tr>
          <th>Level</th>
          ${AQ_POLLUTANTS.map(p => `<th>${p}</th>`).join("")}
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="aq-levels-help-unit">Values are 1-hour average concentrations in µg/m³.</div>
    <div class="aq-levels-help-note">Air quality levels are defined based on this table according to official standards. Air quality is measured hourly for each pollutant and classified into a level. The overall air quality level at a monitoring station is determined by the pollutant with the highest severity category.</div>
  `;
}

// The table is identical for every station, so a single portal element is
// created lazily and appended straight to <body> — that keeps it completely
// outside the Leaflet popup's own DOM/stacking context, so it's guaranteed
// to render above the popup's content (e.g. the pollutant bar chart)
// regardless of any stacking-context quirks inside the popup itself.
var aqLevelsHelpPortalEl = null;

function getAqLevelsHelpPortal() {
  if (!aqLevelsHelpPortalEl) {
    aqLevelsHelpPortalEl = document.createElement("div");
    aqLevelsHelpPortalEl.className = "aq-levels-help-panel";
    aqLevelsHelpPortalEl.innerHTML = aqLevelsHelpInnerHTML();
    document.body.appendChild(aqLevelsHelpPortalEl);
  }
  return aqLevelsHelpPortalEl;
}

function closeAqLevelsHelp() {
  if (aqLevelsHelpPortalEl) aqLevelsHelpPortalEl.classList.remove("open");
}

function toggleAqLevelsHelp(btn) {
  const panel = getAqLevelsHelpPortal();
  const wasOpen = panel.classList.contains("open");
  closeAqLevelsHelp();
  if (wasOpen) return;
  const rect = btn.getBoundingClientRect();
  panel.style.top = (rect.bottom + 10) + "px";
  panel.style.right = (window.innerWidth - rect.right) + "px";
  panel.classList.add("open");
}

// Close the portal whenever any popup closes, so it never sits open and
// orphaned after the station popup it belongs to has gone away.
map.on("popupclose", closeAqLevelsHelp);

var airQualityLayer = L.layerGroup();
var aqMarkersByName = new Map();

function parseAqMonthKeyFromFilename(filename) {
  const match = String(filename || "").match(/(\d{4})\.(\d{2})-daily\.json$/);
  return match ? `${match[1]}-${match[2]}` : null;
}

function formatMonthShort(key) {
  const match = String(key || "").match(/^(\d{4})-(\d{1,2})$/);
  if (!match) return String(key || "-");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const mm = parseInt(match[2], 10);
  return `${MONTHS[mm - 1] || "?"} ${match[1]}`;
}

function getStationDisplayName(fullName) {
  const raw = String(fullName || "").trim();
  const spaceIdx = raw.indexOf(" ");
  return spaceIdx === -1 ? raw : raw.slice(0, spaceIdx);
}

function isRigaStation(station) {
  return String(station && station.name || "").trim().startsWith("Rīga");
}

function aqModeLevel(counts) {
  let best = null, bestCount = 0;
  AQ_LEVELS.forEach(lvl => {
    const c = counts[lvl] || 0;
    if (c > bestCount) { bestCount = c; best = lvl; }
  });
  return best;
}

function loadAirQualityStations() {
  return Promise.all(AQ_FILES.map(f =>
    fetch(f + "?v=" + Date.now())
      .then(r => r.json())
      .then(data => ({ key: parseAqMonthKeyFromFilename(f), data }))
      .catch(err => {
        console.error("[map] Failed to load air quality file", f, err);
        return null;
      })
  )).then(results => {
    const stationsByName = new Map();

    results.filter(Boolean).forEach(({ key, data }) => {
      (Array.isArray(data) ? data : []).forEach(entry => {
        if (!entry || !entry.station) return;

        let station = stationsByName.get(entry.station);
        if (!station) {
          const coords = entry.geom && entry.geom.coordinates;
          let lat = null, lon = null;
          if (Array.isArray(coords) && coords.length === 2) {
            const wgs84 = lks92ToWgs84(coords[0], coords[1]);
            lon = wgs84[0];
            lat = wgs84[1];
          }
          station = { name: entry.station, lat, lon, months: [] };
          stationsByName.set(entry.station, station);
        }

        const daysByNum = {};
        (Array.isArray(entry.days) ? entry.days : []).forEach(day => {
          const dayNum = parseInt(String(day.date || "").slice(-2), 10);
          if (dayNum) daysByNum[dayNum] = day;
        });

        station.months.push({ key, label: formatMonthShort(key), days: daysByNum });
      });
    });

    const stations = Array.from(stationsByName.values()).filter(isRigaStation);
    stations.forEach(s => s.months.sort((a, b) => String(a.key).localeCompare(String(b.key))));
    return stations;
  });
}

var AQ_TIP_STYLE = `
  <style>
    .aq-tip-group { cursor: default; }
    .aq-tip { opacity: 0; pointer-events: none; transition: opacity 0.12s ease; }
    .aq-tip-group:hover .aq-tip { opacity: 1; }
  </style>
`;

function aqHeatmapSVG(months) {
  const cols = 31;
  const cellSize = 15, cellGap = 2;
  const labelW = 62;
  const tipBandH = 24;
  const headerH = tipBandH + 16;
  const rowStep = cellSize + cellGap;
  const w = labelW + cols * rowStep - cellGap;
  const h = headerH + months.length * rowStep - cellGap;
  const tipCx = w / 2;

  let dayHeaderMarkup = "";
  for (let d = 1; d <= cols; d++) {
    if (d === 1 || d % 5 === 0) {
      const x = labelW + (d - 1) * rowStep + cellSize / 2;
      dayHeaderMarkup += `<text x="${x}" y="${headerH - 5}" font-size="8.5" fill="#7a8aa0" text-anchor="middle">${d}</text>`;
    }
  }

  let rowsMarkup = "";
  months.forEach((month, rIdx) => {
    const y = headerH + rIdx * rowStep;
    rowsMarkup += `<text x="${labelW - 8}" y="${y + cellSize / 2 + 3.5}" font-size="9.5" fill="#4a5a70" text-anchor="end">${month.label}</text>`;
    for (let d = 1; d <= cols; d++) {
      const x = labelW + (d - 1) * rowStep;
      const dayInfo = month.days[d];
      const level = dayInfo ? dayInfo.daily_level : null;
      const fill = level && AQ_LEVEL_COLORS[level] ? AQ_LEVEL_COLORS[level] : (dayInfo ? AQ_FALLBACK_COLOR : "#eef1f5");
      const tipText = dayInfo
        ? `${dayInfo.date} — ${level || "No data"}${dayInfo.main_pollutant ? " (" + dayInfo.main_pollutant + ")" : ""}`
        : "";
      rowsMarkup += `
        <g class="aq-tip-group">
          <rect x="${x}" y="${y}" width="${cellSize}" height="${cellSize}" rx="3" ry="3" fill="${fill}" stroke="rgba(15,23,42,0.12)" stroke-width="1"/>
          ${tipText ? `
            <g class="aq-tip">
              <rect x="${tipCx - 95}" y="2" width="190" height="20" rx="6" fill="rgba(17,24,39,0.92)"/>
              <text x="${tipCx}" y="16" text-anchor="middle" font-size="9.5" fill="#ffffff">${tipText}</text>
            </g>
          ` : ""}
        </g>
      `;
    }
  });

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block;">
      ${AQ_TIP_STYLE}
      ${dayHeaderMarkup}
      ${rowsMarkup}
    </svg>
  `;
}

function aqLegendHTML() {
  return AQ_LEVELS.map(lvl => `
    <div class="aq-legend-item">
      <span class="aq-legend-swatch" style="background:${AQ_LEVEL_COLORS[lvl]}"></span>
      <span>${lvl}</span>
    </div>
  `).join("");
}

function aqPieChartSVG(counts, total) {
  const w = 150, h = 132, cx = 75, cy = 80, r = 48;

  if (!total) {
    return `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#e8eef5" stroke-width="2"/>
        <text x="${cx}" y="${cy + 4}" text-anchor="middle" font-size="11" fill="#71839c">No data</text>
      </svg>
    `;
  }

  let acc = 0;
  let slices = "";
  AQ_LEVELS.forEach(lvl => {
    const val = counts[lvl] || 0;
    if (!val) return;
    const frac = val / total;
    const startAngle = acc * 2 * Math.PI - Math.PI / 2;
    acc += frac;
    const endAngle = acc * 2 * Math.PI - Math.PI / 2;

    const color = AQ_LEVEL_COLORS[lvl];
    const pct = Math.round(frac * 100);
    const tip = `
      <g class="aq-tip">
        <rect x="${cx - 65}" y="2" width="130" height="20" rx="6" fill="rgba(17,24,39,0.92)"/>
        <text x="${cx}" y="16" text-anchor="middle" font-size="10.5" fill="#ffffff">${lvl}: ${pct}% (${val} day${val === 1 ? "" : "s"})</text>
      </g>
    `;

    if (frac >= 0.9999) {
      slices += `
        <g class="aq-tip-group">
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}" stroke="#fff" stroke-width="1.5"/>
          ${tip}
        </g>
      `;
      return;
    }

    const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle), y2 = cy + r * Math.sin(endAngle);
    const largeArc = frac > 0.5 ? 1 : 0;
    const path = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
    slices += `
      <g class="aq-tip-group">
        <path d="${path}" fill="${color}" stroke="#fff" stroke-width="1.5"/>
        ${tip}
      </g>
    `;
  });

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      ${AQ_TIP_STYLE}
      ${slices}
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="rgba(15,23,42,0.15)" stroke-width="1.2"/>
    </svg>
  `;
}

function aqPollutantBarSVG(counts, total) {
  const w = 176, h = 140;
  const pad = { l: 4, r: 4, t: 28, b: 20 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const n = AQ_POLLUTANTS.length;
  const gap = 7;
  const barW = (plotW - gap * (n - 1)) / n;
  const maxV = Math.max(1, ...AQ_POLLUTANTS.map(p => counts[p] || 0));
  const tipCx = w / 2;

  if (!total) {
    return `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <line x1="${pad.l}" y1="${pad.t + plotH}" x2="${w - pad.r}" y2="${pad.t + plotH}" stroke="#dde5ef"/>
        <text x="${w / 2}" y="${pad.t + plotH / 2 + 4}" text-anchor="middle" font-size="11" fill="#71839c">No data</text>
      </svg>
    `;
  }

  let bars = "";
  AQ_POLLUTANTS.forEach((pollutant, i) => {
    const val = counts[pollutant] || 0;
    const barH = val ? Math.max((val / maxV) * plotH, 2) : 0;
    const x = pad.l + i * (barW + gap);
    const color = AQ_POLLUTANT_BAR_COLOR;
    const pct = Math.round((val / total) * 100);
    const y = pad.t + plotH - barH;

    bars += `
      <g class="aq-tip-group">
        <rect x="${x}" y="${pad.t}" width="${barW}" height="${plotH}" fill="transparent"/>
        ${val
          ? `<rect x="${x}" y="${y}" width="${barW}" height="${barH}" rx="2.5" ry="2.5" fill="${color}" stroke="rgba(15,23,42,0.15)" stroke-width="1"/>`
          : `<rect x="${x}" y="${pad.t + plotH - 2}" width="${barW}" height="2" rx="1" fill="#e3e8ef"/>`}
        <text x="${x + barW / 2}" y="${h - 6}" text-anchor="middle" font-size="8" fill="#5f6b7a">${pollutant}</text>
        <g class="aq-tip">
          <rect x="${tipCx - 75}" y="2" width="150" height="20" rx="6" fill="rgba(17,24,39,0.92)"/>
          <text x="${tipCx}" y="16" text-anchor="middle" font-size="10" fill="#ffffff">${pollutant}: ${val} day${val === 1 ? "" : "s"} (${pct}%)</text>
        </g>
      </g>
    `;
  });

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      ${AQ_TIP_STYLE}
      <line x1="${pad.l}" y1="${pad.t + plotH}" x2="${w - pad.r}" y2="${pad.t + plotH}" stroke="#dde5ef"/>
      ${bars}
    </svg>
  `;
}

function buildAirQualityPopupContent(station) {
  const months = Array.isArray(station.months) ? station.months : [];
  const latestMonth = months.length ? months[months.length - 1] : null;

  const counts = {};
  const pollutantCounts = {};
  let total = 0;
  if (latestMonth) {
    Object.values(latestMonth.days).forEach(day => {
      if (!day || !day.daily_level) return;
      counts[day.daily_level] = (counts[day.daily_level] || 0) + 1;
      total += 1;
      if (day.main_pollutant) {
        pollutantCounts[day.main_pollutant] = (pollutantCounts[day.main_pollutant] || 0) + 1;
      }
    });
  }

  const monthlyLevel = aqModeLevel(counts);
  const monthlyLevelColor = monthlyLevel ? AQ_LEVEL_COLORS[monthlyLevel] : AQ_FALLBACK_COLOR;

  const pieLegendRows = AQ_LEVELS.filter(lvl => counts[lvl]).map(lvl => `
    <div class="aq-pie-legend-row">
      <span class="aq-legend-swatch" style="background:${AQ_LEVEL_COLORS[lvl]}"></span>
      <span class="aq-pie-legend-label">${lvl}</span>
    </div>
  `).join("");

  const latestMonthLabel = latestMonth ? formatMonthYear(latestMonth.key) : "-";

  return `
    <div class="aq-popup">
      <div class="aq-popup-header">
        <h3 class="aq-title">Air quality observation station</h3>
        <div class="aq-subtitle">Station: ${getStationDisplayName(station.name)}</div>
      </div>

      <div class="aq-section">
        <div class="aq-latest-head">
          <h4 class="section-title">Latest month <span class="aq-latest-month-label">(${latestMonthLabel})</span></h4>
          <div class="aq-latest-head-right">
            <span class="aq-badge" style="background:${monthlyLevelColor};">${monthlyLevel || "No data"}</span>
            <button type="button" class="legend-help-btn" aria-label="Explain air quality levels" onclick="event.stopPropagation(); toggleAqLevelsHelp(this);">?</button>
          </div>
        </div>
        <div class="panel-card aq-latest-card">
          <div class="aq-latest-col">
            <div class="aq-mini-title">Air quality level</div>
            <div class="aq-pie-row">
              <div class="aq-pie-wrap">${aqPieChartSVG(counts, total)}</div>
              <div class="aq-pie-legend">${pieLegendRows || '<div class="kpi-sub">No data available</div>'}</div>
            </div>
          </div>
          <div class="aq-latest-divider"></div>
          <div class="aq-latest-col">
            <div class="aq-mini-title">Main pollutant by day</div>
            <div class="aq-pollutant-wrap">${aqPollutantBarSVG(pollutantCounts, total)}</div>
          </div>
        </div>
      </div>

      <div class="aq-section">
        <h4 class="section-title">Last year's air quality summary</h4>
        <div class="panel-card aq-heatmap-card">
          <div class="aq-heatmap-wrap">${months.length ? aqHeatmapSVG(months) : '<div class="kpi-sub" style="padding:10px;text-align:center;">No data available</div>'}</div>
          <div class="aq-legend-row">${aqLegendHTML()}</div>
        </div>
      </div>
    </div>
  `;
}

function aqMarkerColor(station) {
  const months = Array.isArray(station.months) ? station.months : [];
  const latestMonth = months.length ? months[months.length - 1] : null;
  if (!latestMonth) return AQ_FALLBACK_COLOR;

  const dayNums = Object.keys(latestMonth.days).map(Number).filter(n => !isNaN(n)).sort((a, b) => a - b);
  const lastDayNum = dayNums.length ? dayNums[dayNums.length - 1] : null;
  const lastDay = lastDayNum ? latestMonth.days[lastDayNum] : null;
  return (lastDay && AQ_LEVEL_COLORS[lastDay.daily_level]) || AQ_FALLBACK_COLOR;
}

var AQ_PIN_SVG = color => `
  <svg width="20" height="27" viewBox="0 0 20 27" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 0C4.48 0 0 4.48 0 10c0 7.5 10 17 10 17s10-9.5 10-17C20 4.48 15.52 0 10 0z"
          fill="#ffffff" stroke="#5f6b7a" stroke-width="1.3"/>
    <circle cx="10" cy="10" r="5.2" fill="${color}" stroke="#ffffff" stroke-width="1"/>
  </svg>
`;

var STATION_PIN_TIP_X = 10;

function shiftedPinAnchors(shiftX) {
  const dx = shiftX || 0;
  return {
    iconAnchor: [STATION_PIN_TIP_X - dx, 27],
    popupAnchor: [dx, -25],
    tooltipAnchor: [dx, -25]
  };
}

function createAqIcon(color, shiftX) {
  const anchors = shiftedPinAnchors(shiftX);
  return L.divIcon({
    className: "aq-marker-icon",
    html: AQ_PIN_SVG(color),
    iconSize: [20, 27],
    iconAnchor: anchors.iconAnchor,
    popupAnchor: anchors.popupAnchor,
    tooltipAnchor: anchors.tooltipAnchor
  });
}

function renderAirQualityStations(stations, shiftByName) {
  airQualityLayer.clearLayers();
  aqMarkersByName.clear();
  let placed = 0;

  (Array.isArray(stations) ? stations : []).forEach(station => {
    try {
      if (typeof station.lat !== "number" || typeof station.lon !== "number" || !isFinite(station.lat) || !isFinite(station.lon)) {
        console.warn("[map] Air quality station has no valid coordinates, skipping:", station && station.name);
        return;
      }

      const shiftX = (shiftByName && shiftByName.get(station.name)) || 0;
      const marker = L.marker([station.lat, station.lon], {
        icon: createAqIcon(aqMarkerColor(station), shiftX),
        zIndexOffset: 1000
      });

      marker.bindTooltip(getStationDisplayName(station.name), { direction: "top", offset: [0, -8] });
      marker.bindPopup(function () {
        return buildAirQualityPopupContent(station);
      }, Object.assign({ maxWidth: 700 }, POPUP_AUTOPAN_PADDING));
      marker.addTo(airQualityLayer);
      aqMarkersByName.set(station.name, marker);
      placed += 1;
    } catch (err) {
      console.error("[map] Failed to render air quality station marker:", station && station.name, err);
    }
  });

  airQualityLayer.addTo(map);
  console.log("[map] Air quality markers placed:", placed, "of", (stations || []).length, "| station coords:",
    (stations || []).map(s => `${getStationDisplayName(s.name)}: ${s.lat}, ${s.lon}`));

  renderAqStationCard(stations);
}

function goToAqStation(stationName) {
  const marker = aqMarkersByName.get(stationName);
  if (!marker) return;

  const latlng = marker.getLatLng();
  let popupOpened = false;
  const openPopup = function () {
    if (popupOpened) return;
    popupOpened = true;
    marker.openPopup();
  };

  map.once("moveend", openPopup);
  map.flyTo(latlng, Math.max(map.getZoom(), 17), { animate: true, duration: 0.6 });
  window.setTimeout(openPopup, 700);
}

function renderAqStationCard(stations) {
  const cardEl = document.getElementById("aq-station-card");
  const listEl = document.getElementById("aq-station-list");
  if (!cardEl || !listEl) return;

  const validStations = (Array.isArray(stations) ? stations : []).filter(s => aqMarkersByName.has(s.name)).reverse();
  if (!validStations.length) {
    cardEl.hidden = true;
    return;
  }

  listEl.innerHTML = validStations.map(station => `
    <button type="button" class="aq-station-btn" data-station="${encodeURIComponent(station.name)}">
      <span class="aq-station-dot" style="background:${aqMarkerColor(station)};"></span>
      <span class="aq-station-name">${getStationDisplayName(station.name)}</span>
    </button>
  `).join("");

  listEl.querySelectorAll("[data-station]").forEach(btn => {
    btn.addEventListener("click", function () {
      goToAqStation(decodeURIComponent(btn.getAttribute("data-station")));
    });
  });

  cardEl.hidden = false;
}

/* ═══════════════════════════════════════════════════
   METEOROLOGICAL STATIONS
═══════════════════════════════════════════════════ */
var METEO_FILE = DATA_BASE_URL + "meteo_stations.csv";
var meteoLayer = L.layerGroup();
var meteoMarkersByName = new Map();

var MET_PIN_SVG = `
  <svg width="20" height="27" viewBox="0 0 20 27" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 0C4.48 0 0 4.48 0 10c0 7.5 10 17 10 17s10-9.5 10-17C20 4.48 15.52 0 10 0z"
          fill="#5b7fa6" stroke="#38556f" stroke-width="1.3"/>
    <circle cx="10" cy="10" r="5.2" fill="#ffffff" stroke="#5b7fa6" stroke-width="1"/>
  </svg>
`;

function createMeteoIcon(shiftX) {
  const anchors = shiftedPinAnchors(shiftX);
  return L.divIcon({
    className: "aq-marker-icon",
    html: MET_PIN_SVG,
    iconSize: [20, 27],
    iconAnchor: anchors.iconAnchor,
    popupAnchor: anchors.popupAnchor,
    tooltipAnchor: anchors.tooltipAnchor
  });
}

function parseMeteoCsv(text) {
  const lines = String(text || "").split(/\r?\n/).filter(l => l.trim().length);
  if (!lines.length) return [];

  const header = lines[0].split(",").map(h => h.trim());
  const idx = {};
  header.forEach((h, i) => { idx[h] = i; });

  return lines.slice(1).map(line => {
    const cols = line.split(",");
    const name = (cols[idx.NAME] || "").trim();
    const lon = parseFloat(cols[idx.GEOGR1]);
    const lat = parseFloat(cols[idx.GEOGR2]);
    const wmoRaw = (cols[idx.WMO_ID] || "").trim();
    const elevationRaw = (cols[idx.ELEVATION] || "").trim();
    const elevation = elevationRaw ? parseFloat(elevationRaw) : null;
    const beginDate = (cols[idx.BEGIN_DATE] || "").trim();

    return {
      id: (cols[idx.STATION_ID] || "").trim(),
      name: name || "Meteorological station",
      lat: isFinite(lat) ? lat : null,
      lon: isFinite(lon) ? lon : null,
      wmoId: wmoRaw || null,
      elevation: isFinite(elevation) ? elevation : null,
      beginDate: beginDate || null
    };
  }).filter(s => s.lat !== null && s.lon !== null);
}

var METEO_RIGA_EXTRA_NAMES = ["Daugavgrīva"];

function isRigaMeteoStation(station) {
  if (isRigaStation(station)) return true;
  const name = String(station && station.name || "").trim();
  return METEO_RIGA_EXTRA_NAMES.includes(name);
}

/* Hourly hourly-observation CSVs (meteo_data_<STATION_ID>.csv) only cover
   measures we're allowed to show; aggregate them to the same 12-month
   window the air-quality data uses, for month-to-month alignment.
   The most recent (in-progress) calendar month is intentionally excluded
   since it isn't a complete month of readings yet. */
var METEO_MEASURES = ["HTDRY", "HATMN", "HRLH", "HSNOW", "HPRAB", "HWDAV", "HWNDS"];
var METEO_MONTH_KEYS = AQ_FILES.map(parseAqMonthKeyFromFilename);

function parseMeteoHourlyCsv(text) {
  const lines = String(text || "").split(/\r?\n/).filter(l => l.trim().length);
  if (!lines.length) return [];

  const header = lines[0].split(",").map(h => h.trim());
  const idx = {};
  header.forEach((h, i) => { idx[h] = i; });

  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",");
    const abbr = (cols[idx.ABBREVIATION] || "").trim();
    if (METEO_MEASURES.indexOf(abbr) === -1) continue;

    const datetime = (cols[idx.DATETIME] || "").trim();
    const monthKey = datetime.slice(0, 7);
    if (METEO_MONTH_KEYS.indexOf(monthKey) === -1) continue;

    const raw = (cols[idx.VALUE] || "").trim();
    if (raw === "") continue;
    const value = parseFloat(raw);
    if (!isFinite(value)) continue;

    const hour = parseInt(datetime.slice(11, 13), 10);
    rows.push({ abbr, monthKey, value, hour: isFinite(hour) ? hour : null });
  }
  return rows;
}

function emptyMeteoMonths() {
  return METEO_MONTH_KEYS.map(k => ({
    key: k, label: formatMonthShort(k),
    temp: null, tempDay: null, tempNight: null, tempMin: null, humidity: null,
    windSpeed: null, windDir: null,
    precipitation: 0, snowDepth: 0
  }));
}

function aggregateMeteoMonthly(rows) {
  const buckets = new Map();
  METEO_MONTH_KEYS.forEach(k => buckets.set(k, {
    HTDRY: { sum: 0, count: 0 },
    HTDRY_DAY: { sum: 0, count: 0 },
    HTDRY_NIGHT: { sum: 0, count: 0 },
    HATMN: { min: Infinity, has: false },
    HRLH: { sum: 0, count: 0 },
    HWNDS: { sum: 0, count: 0 },
    HWDAV: { sinSum: 0, cosSum: 0, count: 0 },
    HPRAB: { sum: 0 },
    HSNOW: { max: 0, has: false }
  }));

  rows.forEach(r => {
    const b = buckets.get(r.monthKey);
    if (!b) return;
    if (r.abbr === "HPRAB") { b.HPRAB.sum += r.value; return; }
    if (r.abbr === "HSNOW") { b.HSNOW.has = true; b.HSNOW.max = Math.max(b.HSNOW.max, r.value); return; }
    if (r.abbr === "HATMN") { b.HATMN.has = true; b.HATMN.min = Math.min(b.HATMN.min, r.value); return; }
    if (r.abbr === "HWDAV") {
      const rad = r.value * Math.PI / 180;
      b.HWDAV.sinSum += Math.sin(rad);
      b.HWDAV.cosSum += Math.cos(rad);
      b.HWDAV.count += 1;
      return;
    }
    if (r.abbr === "HTDRY") {
      b.HTDRY.sum += r.value;
      b.HTDRY.count += 1;
      if (r.hour !== null) {
        const isDaytime = r.hour >= 7 && r.hour < 22;
        const dnBucket = isDaytime ? b.HTDRY_DAY : b.HTDRY_NIGHT;
        dnBucket.sum += r.value;
        dnBucket.count += 1;
      }
      return;
    }
    const bucket = b[r.abbr];
    if (!bucket) return;
    bucket.sum += r.value;
    bucket.count += 1;
  });

  return METEO_MONTH_KEYS.map(k => {
    const b = buckets.get(k);
    const avg = m => (b[m].count ? b[m].sum / b[m].count : null);
    const windDir = b.HWDAV.count
      ? ((Math.atan2(b.HWDAV.sinSum, b.HWDAV.cosSum) * 180 / Math.PI) + 360) % 360
      : null;

    return {
      key: k,
      label: formatMonthShort(k),
      temp: avg("HTDRY"),
      tempDay: avg("HTDRY_DAY"),
      tempNight: avg("HTDRY_NIGHT"),
      tempMin: b.HATMN.has ? b.HATMN.min : null,
      humidity: avg("HRLH"),
      windSpeed: avg("HWNDS"),
      windDir: windDir,
      precipitation: b.HPRAB.sum,
      snowDepth: b.HSNOW.has ? b.HSNOW.max : 0
    };
  });
}

function loadMeteoHourlyData(stationId) {
  if (!stationId) return Promise.resolve(emptyMeteoMonths());
  return fetch(`${DATA_BASE_URL}meteo_data_${stationId}.csv?v=` + Date.now())
    .then(r => r.text())
    .then(parseMeteoHourlyCsv)
    .then(aggregateMeteoMonthly)
    .catch(err => {
      console.error("[map] Failed to load meteo hourly data for", stationId, err);
      return emptyMeteoMonths();
    });
}

function loadMeteoStations() {
  return fetch(METEO_FILE + "?v=" + Date.now())
    .then(r => r.text())
    .then(parseMeteoCsv)
    .then(stations => stations.filter(isRigaMeteoStation))
    .then(stations => Promise.all(stations.map(station =>
      loadMeteoHourlyData(station.id).then(monthly => {
        station.monthly = monthly;
        return station;
      })
    )));
}

function fmtC(v) {
  return (v === null || v === undefined || !isFinite(v)) ? "-" : `${v.toFixed(1)}°C`;
}

function fmtCm(v) {
  return (v === null || v === undefined || !isFinite(v)) ? "-" : `${v.toFixed(1)} cm`;
}

function fmtMm(v) {
  return (v === null || v === undefined || !isFinite(v)) ? "-" : `${v.toFixed(1)} mm`;
}

function fmtWindSpeed(v) {
  return (v === null || v === undefined || !isFinite(v)) ? "-" : `${v.toFixed(1)} m/s`;
}

function windDirLabel(deg) {
  if (deg === null || deg === undefined || !isFinite(deg)) return "-";
  const dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const idx = Math.round(deg / 22.5) % 16;
  return `${Math.round(deg)}° ${dirs[idx]}`;
}

function windCompassSVG(dirDeg, speed) {
  const w = 48, h = 50, cx = 24, cy = 29, r = 15;

  if (dirDeg === null || dirDeg === undefined || !isFinite(dirDeg)) {
    return `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="#f7f9fb" stroke="#dde5ef" stroke-width="1.3"/>
        <text x="${cx}" y="${cy + 3}" text-anchor="middle" font-size="8" fill="#9aa8bc">-</text>
      </svg>
    `;
  }

  const rad = (dirDeg - 90) * Math.PI / 180;
  const tipX = cx + r * 0.8 * Math.cos(rad);
  const tipY = cy + r * 0.8 * Math.sin(rad);
  const tailRad = rad + Math.PI;
  const tailX = cx + r * 0.38 * Math.cos(tailRad);
  const tailY = cy + r * 0.38 * Math.sin(tailRad);

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="#f7f9fb" stroke="#dde5ef" stroke-width="1.3"/>
      <text x="${cx}" y="${cy - r - 5}" text-anchor="middle" font-size="7.5" fill="#9aa8bc">N</text>
      <line x1="${tailX}" y1="${tailY}" x2="${tipX}" y2="${tipY}" stroke="#5b7fa6" stroke-width="2.6" stroke-linecap="round"/>
      <circle cx="${tipX}" cy="${tipY}" r="2.6" fill="#5b7fa6"/>
      <circle cx="${cx}" cy="${cy}" r="1.8" fill="#5b7fa6"/>
    </svg>
  `;
}

function humidityGaugeHTML(pct) {
  const hasValue = pct !== null && pct !== undefined && isFinite(pct);
  const safePct = hasValue ? Math.max(0, Math.min(100, pct)) : 0;
  const label = hasValue ? `${Math.round(pct)}%` : "-";

  return `
    <div class="meteo-gauge">
      <div class="meteo-gauge-track">
        <div class="meteo-gauge-fill" style="width:${safePct}%;"></div>
      </div>
      <div class="meteo-gauge-label">${label}</div>
    </div>
  `;
}

/* "Nice" rounded axis bound that preserves sign, so a negative minimum
   (e.g. winter temperatures) gets a sensible negative floor instead of
   being clamped to zero like the always-positive building chart. */
function niceBound(v) {
  if (v === 0) return 0;
  const sign = v < 0 ? -1 : 1;
  const av = Math.abs(v);
  const exp = Math.floor(Math.log10(av));
  const f = av / Math.pow(10, exp);
  let niceF;
  if (f <= 1) niceF = 1;
  else if (f <= 2) niceF = 2;
  else if (f <= 5) niceF = 5;
  else niceF = 10;
  return sign * niceF * Math.pow(10, exp);
}

var METEO_METRIC_CONFIGS = [
  { key: "temp", label: "Average temperature", field: "temp", unit: " °C", decimals: 1 },
  { key: "humidity", label: "Average humidity", field: "humidity", unit: "%", decimals: 0 },
  { key: "wind", label: "Average wind speed", field: "windSpeed", unit: " m/s", decimals: 1 },
  { key: "snow", label: "Maximum snow depth", field: "snowDepth", unit: " cm", decimals: 1 },
  { key: "precip", label: "Total precipitation", field: "precipitation", unit: " mm", decimals: 1 }
];

function meteoSelectMetric(btn, metric) {
  const card = btn.closest(".meteo-trend-card");
  if (!card) return;
  card.querySelectorAll(".meteo-metric-btn").forEach(b => b.classList.toggle("active", b === btn));
  card.querySelectorAll(".meteo-metric-plot").forEach(p => { p.hidden = p.getAttribute("data-metric") !== metric; });
}

/* Same visual language as the building popup's heat-consumption line chart
   (bezier curve, gradient area, hover dots/tooltips), generalized to:
   - scale its y-axis to whatever range the metric actually needs, and
   - keep negative values (sub-zero temperatures) inside the plot with a
     visible zero line, instead of assuming a 0-based baseline. */
function meteoTrendChartSVG(monthKeys, values, opts) {
  opts = opts || {};
  const decimals = opts.decimals ?? 1;
  const unit = opts.unit || "";

  const nums = values.map(v => (v === null || v === undefined || !isFinite(v)) ? null : v);
  const validNums = nums.filter(v => v !== null);

  const w = 460, h = 144;
  const pad = { l: 48, r: 18, t: 14, b: 32 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;

  if (!validNums.length) {
    return `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
        <rect x="0" y="0" width="${w}" height="${h}" rx="10" ry="10" fill="#fdfefe"/>
        <text x="${w / 2}" y="${h / 2 + 4}" text-anchor="middle" font-size="11" fill="#71839c">No data</text>
      </svg>
    `;
  }

  const filled = nums.map(v => v === null ? 0 : v);
  const rawMax = Math.max(...validNums, 0);
  const rawMin = Math.min(...validNums, 0);
  const yMax = rawMax > 0 ? niceBound(rawMax) : (rawMin < 0 ? 0 : 1);
  const yMin = rawMin < 0 ? niceBound(rawMin) : 0;
  const range = (yMax - yMin) || 1;

  const stepX = filled.length > 1 ? plotW / (filled.length - 1) : plotW;
  const xAt = i => pad.l + i * stepX;
  const yAt = v => pad.t + plotH - ((v - yMin) / range) * plotH;
  const zeroY = yAt(0);

  const last = filled.length - 1;
  const prev = last - 1;
  const latestDotColor = "#176087";
  const previousDotColor = "#1f5ed8";
  const defaultDotColor = "#5e95f5";

  const points = filled.map((v, i) => ({ x: xAt(i), y: yAt(v), v, i }));

  function pointAt(idx) {
    if (idx < 0) return points[0];
    if (idx >= points.length) return points[points.length - 1];
    return points[idx];
  }

  function getSegmentBezier(i) {
    const p0 = pointAt(i - 1);
    const p1 = pointAt(i);
    const p2 = pointAt(i + 1);
    const p3 = pointAt(i + 2);
    const tension = 1;
    const cp1x = p1.x + ((p2.x - p0.x) / 6) * tension;
    const cp1y = p1.y + ((p2.y - p0.y) / 6) * tension;
    const cp2x = p2.x - ((p3.x - p1.x) / 6) * tension;
    const cp2y = p2.y - ((p3.y - p1.y) / 6) * tension;
    return { cp1x, cp1y, cp2x, cp2y, p1, p2 };
  }

  let smoothPath = "";
  if (points.length > 0) {
    smoothPath = `M ${points[0].x} ${points[0].y} `;
    for (let i = 0; i < points.length - 1; i++) {
      const seg = getSegmentBezier(i);
      smoothPath += `C ${seg.cp1x} ${seg.cp1y}, ${seg.cp2x} ${seg.cp2y}, ${seg.p2.x} ${seg.p2.y} `;
    }
  }

  const areaPath = points.length > 0
    ? `${smoothPath} L ${points[points.length - 1].x} ${zeroY} L ${points[0].x} ${zeroY} Z`
    : "";

  const ticks = 4;
  let yTicks = "";
  for (let i = 0; i <= ticks; i++) {
    const val = yMin + (range / ticks) * i;
    const yy = yAt(val);
    yTicks += `
      <line x1="${pad.l}" y1="${yy}" x2="${w - pad.r}" y2="${yy}" stroke="#dde5ef" stroke-dasharray="3,3"/>
      <text x="${pad.l - 8}" y="${yy + 4}" font-size="9.5" fill="#5f6b7a" text-anchor="end">${val.toFixed(decimals)}${unit}</text>
    `;
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  let xTicks = "";
  monthKeys.forEach((k, i) => {
    const match = String(k).match(/^(\d{4})-(\d{1,2})$/);
    const mm = match ? parseInt(match[2], 10) : null;
    const label = mm ? MONTHS[mm - 1] : "";
    xTicks += `<text x="${xAt(i)}" y="${h - 9}" font-size="10" fill="#5f6b7a" text-anchor="middle">${label}</text>`;
  });

  const zeroLineMarkup = (yMin < 0 && yMax > 0)
    ? `<line x1="${pad.l}" y1="${zeroY}" x2="${w - pad.r}" y2="${zeroY}" stroke="#8d98a8"/>`
    : "";

  let pointMarkup = "";
  nums.forEach((v, i) => {
    if (v === null) return;
    const isLatest = i === last;
    const isPrevious = i === prev;
    const r = isLatest ? 5.5 : (isPrevious ? 4.8 : 3.7);
    const fill = isLatest ? latestDotColor : (isPrevious ? previousDotColor : defaultDotColor);
    const valueText = `${v.toFixed(decimals)}${unit}`;

    let tipRectY = yAt(v) - 30;
    if (tipRectY < 2) tipRectY = yAt(v) + 14;
    if (tipRectY > h - 18) tipRectY = h - 18;
    const tipTextY = tipRectY + 11;
    let tipCx = xAt(i);
    if (tipCx - 35 < 2) tipCx = 35 + 2;
    if (tipCx + 35 > w - 2) tipCx = w - 2 - 35;

    pointMarkup += `
      <g class="dot-group" style="pointer-events:all;cursor:default;">
        <circle cx="${xAt(i)}" cy="${yAt(v)}" r="8" fill="transparent"/>
        <circle class="chart-dot" cx="${xAt(i)}" cy="${yAt(v)}" r="${r}" fill="${fill}" stroke="#ffffff" stroke-width="1.2">
          <title>${monthKeys[i]} - ${valueText}</title>
        </circle>
        <g class="chart-tip">
          <rect x="${tipCx - 35}" y="${tipRectY}" width="70" height="16" rx="5" ry="5" fill="rgba(17,24,39,0.92)"/>
          <text x="${tipCx}" y="${tipTextY}" font-size="9.8" fill="#ffffff" text-anchor="middle">${valueText}</text>
        </g>
      </g>
    `;
  });

  return `
    <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block;pointer-events:auto;">
      <style>
        .dot-group .chart-tip { opacity: 0; pointer-events: none; transition: opacity 0.15s ease; }
        .dot-group .chart-dot { opacity: 0; transition: opacity 0.15s ease; }
        .dot-group:hover .chart-tip,
        .dot-group:hover .chart-dot { opacity: 1; }
      </style>
      <defs>
        <linearGradient id="meteoChartAreaGrad-${opts.gradId || "x"}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(91,127,166,0.26)"/>
          <stop offset="68%" stop-color="rgba(91,127,166,0.10)"/>
          <stop offset="100%" stop-color="rgba(91,127,166,0.01)"/>
        </linearGradient>
      </defs>
      <rect x="0" y="0" width="${w}" height="${h}" rx="10" ry="10" fill="#fdfefe"/>
      ${yTicks}
      <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${h - pad.b}" stroke="#8d98a8"/>
      <line x1="${pad.l}" y1="${h - pad.b}" x2="${w - pad.r}" y2="${h - pad.b}" stroke="#8d98a8"/>
      ${zeroLineMarkup}
      <path d="${areaPath}" fill="url(#meteoChartAreaGrad-${opts.gradId || "x"})"/>
      <path d="${smoothPath}" fill="none" stroke="#5b7fa6" stroke-width="2.25" stroke-linecap="round"/>
      ${pointMarkup}
      ${xTicks}
    </svg>
  `;
}

function buildMeteoPopupContent(station) {
  const months = Array.isArray(station.monthly) ? station.monthly : [];
  const latest = months.length ? months[months.length - 1] : null;
  const previous = months.length > 1 ? months[months.length - 2] : null;
  const latestLabel = latest ? formatMonthYear(latest.key) : "-";
  const prevLabel = previous ? formatMonthYear(previous.key) : "-";

  const tempDelta = (latest && previous && latest.temp !== null && previous.temp !== null)
    ? latest.temp - previous.temp
    : null;
  const tempChangeText = tempDelta === null ? "-" : `${tempDelta > 0 ? "+" : ""}${tempDelta.toFixed(1)}°C`;
  const tempChangeArrow = tempDelta === null ? "" : (tempDelta > 0 ? "▲" : (tempDelta < 0 ? "▼" : "■"));
  const tempChangeClass = tempDelta === null ? "neutral" : (tempDelta > 0 ? "temp-up" : (tempDelta < 0 ? "temp-down" : "neutral"));

  const beginYear = station.beginDate && /^\d{4}/.test(station.beginDate) ? station.beginDate.slice(0, 4) : null;
  const elevationText = station.elevation !== null ? `${station.elevation} m` : "-";

  const monthKeys = months.map(m => m.key);
  const metricButtonsHTML = METEO_METRIC_CONFIGS.map((cfg, idx) => `
    <button type="button" class="meteo-metric-btn${idx === 0 ? " active" : ""}" onclick="meteoSelectMetric(this, '${cfg.key}')">${cfg.label}</button>
  `).join("");
  const metricPlotsHTML = METEO_METRIC_CONFIGS.map((cfg, idx) => {
    const vals = months.map(m => m[cfg.field]);
    const chartSVG = meteoTrendChartSVG(monthKeys, vals, { unit: cfg.unit, decimals: cfg.decimals, gradId: cfg.key });
    return `<div class="meteo-metric-plot" data-metric="${cfg.key}"${idx === 0 ? "" : " hidden"}>${chartSVG}</div>`;
  }).join("");

  return `
    <div class="meteo-popup">
      <div class="meteo-popup-header">
        <h3 class="meteo-title">Meteorological station</h3>
        <div class="meteo-subtitle">Station: ${station.name}</div>
        <div class="meteo-subtitle">Monitoring since: ${beginYear || "-"}</div>
        <div class="meteo-subtitle">Elevation: ${elevationText}</div>
      </div>

      <div class="meteo-popup-body">
        <div class="meteo-section">
          <h4 class="section-title">Temperature summary</h4>
          <div class="kpi-grid meteo-temp-kpis">
            <div class="kpi-card latest-card">
              <div class="kpi-label">Latest month</div>
              <div class="kpi-value latest">${fmtC(latest ? latest.temp : null)}</div>
              <div class="kpi-sub">${latestLabel}</div>
            </div>
            <div class="kpi-card previous-card">
              <div class="kpi-label">Previous month</div>
              <div class="kpi-value previous">${fmtC(previous ? previous.temp : null)}</div>
              <div class="kpi-sub">${prevLabel}</div>
            </div>
            <div class="kpi-card change-card ${tempChangeClass}">
              <div class="kpi-label">Monthly change</div>
              <div class="kpi-change ${tempChangeClass}">${tempChangeArrow} ${tempChangeText}</div>
              <div class="kpi-sub">Average temperature vs previous month</div>
            </div>
          </div>
        </div>

        <div class="meteo-section">
          <h4 class="section-title">Conditions of latest month <span class="aq-latest-month-label">(${latestLabel})</span></h4>
          <div class="meteo-conditions-grid">
            <div class="panel-card meteo-mini-card">
              <div class="aq-mini-title">Min. temperature</div>
              <div class="meteo-mini-content">
                <div class="meteo-stat-value">${fmtC(latest ? latest.tempMin : null)}</div>
              </div>
            </div>
            <div class="panel-card meteo-mini-card">
              <div class="aq-mini-title">Humidity</div>
              <div class="meteo-mini-content">
                ${humidityGaugeHTML(latest ? latest.humidity : null)}
              </div>
            </div>
            <div class="panel-card meteo-mini-card">
              <div class="aq-mini-title">Wind</div>
              <div class="meteo-mini-content">
                <div class="meteo-wind-row">
                  ${windCompassSVG(latest ? latest.windDir : null, latest ? latest.windSpeed : null)}
                  <div class="meteo-wind-values">
                    <div class="meteo-stat-value">${fmtWindSpeed(latest ? latest.windSpeed : null)}</div>
                    <div class="kpi-sub">${windDirLabel(latest ? latest.windDir : null)}</div>
                  </div>
                </div>
              </div>
            </div>
            <div class="panel-card meteo-mini-card">
              <div class="aq-mini-title">Snow depth</div>
              <div class="meteo-mini-content">
                <div class="meteo-stat-value">${fmtCm(latest ? latest.snowDepth : null)}</div>
                <div class="kpi-sub">(month maximum)</div>
              </div>
            </div>
            <div class="panel-card meteo-mini-card">
              <div class="aq-mini-title">Precipitation</div>
              <div class="meteo-mini-content">
                <div class="meteo-stat-value">${fmtMm(latest ? latest.precipitation : null)}</div>
                <div class="kpi-sub">(month total)</div>
              </div>
            </div>
          </div>
          <div class="meteo-daynight-grid">
            <div class="panel-card meteo-mini-card inline">
              <div class="aq-mini-title">Day-time average temperature</div>
              <div class="meteo-stat-value">${fmtC(latest ? latest.tempDay : null)}</div>
            </div>
            <div class="panel-card meteo-mini-card inline">
              <div class="aq-mini-title">Night-time average temperature</div>
              <div class="meteo-stat-value">${fmtC(latest ? latest.tempNight : null)}</div>
            </div>
          </div>
        </div>

        <div class="meteo-section">
          <h4 class="section-title">Last year's summary</h4>
          <div class="panel-card meteo-trend-card">
            <div class="meteo-metric-buttons">
              ${metricButtonsHTML}
            </div>
            <div class="chart-wrap">
              ${metricPlotsHTML}
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderMeteoStations(stations, shiftByName) {
  meteoLayer.clearLayers();
  meteoMarkersByName.clear();
  let placed = 0;

  (Array.isArray(stations) ? stations : []).forEach(station => {
    try {
      const shiftX = (shiftByName && shiftByName.get(station.name)) || 0;
      const marker = L.marker([station.lat, station.lon], {
        icon: createMeteoIcon(shiftX),
        zIndexOffset: 900
      });

      marker.bindTooltip(station.name, { direction: "top", offset: [0, -8] });
      marker.bindPopup(function () {
        return buildMeteoPopupContent(station);
      }, Object.assign({ maxWidth: 800 }, POPUP_AUTOPAN_PADDING));
      marker.addTo(meteoLayer);
      meteoMarkersByName.set(station.name, marker);
      placed += 1;
    } catch (err) {
      console.error("[map] Failed to render meteo station marker:", station && station.name, err);
    }
  });

  meteoLayer.addTo(map);
  console.log("[map] Meteo stations placed:", placed, "of", (stations || []).length);

  renderMeteoStationCard(stations);
}

function goToMeteoStation(stationName) {
  const marker = meteoMarkersByName.get(stationName);
  if (!marker) return;

  const latlng = marker.getLatLng();
  let popupOpened = false;
  const openPopup = function () {
    if (popupOpened) return;
    popupOpened = true;
    marker.openPopup();
  };

  map.once("moveend", openPopup);
  map.flyTo(latlng, Math.max(map.getZoom(), 17), { animate: true, duration: 0.6 });
  window.setTimeout(openPopup, 700);
}

function renderMeteoStationCard(stations) {
  const cardEl = document.getElementById("meteo-station-card");
  const listEl = document.getElementById("meteo-station-list");
  if (!cardEl || !listEl) return;

  const validStations = (Array.isArray(stations) ? stations : []).filter(s => meteoMarkersByName.has(s.name)).reverse();
  if (!validStations.length) {
    cardEl.hidden = true;
    layoutStationCards();
    return;
  }

  listEl.innerHTML = validStations.map(station => `
    <button type="button" class="aq-station-btn" data-station="${encodeURIComponent(station.name)}">
      <span class="aq-station-dot" style="background:#5b7fa6;"></span>
      <span class="aq-station-name">${station.name}</span>
    </button>
  `).join("");

  listEl.querySelectorAll("[data-station]").forEach(btn => {
    btn.addEventListener("click", function () {
      goToMeteoStation(decodeURIComponent(btn.getAttribute("data-station")));
    });
  });

  cardEl.hidden = false;
  layoutStationCards();
}

/* Stack the meteo card directly above the air-quality card, using its
   actual rendered height so the gap stays correct regardless of how
   many stations either card ends up listing. */
function layoutStationCards() {
  const aqCardEl = document.getElementById("aq-station-card");
  const meteoCardEl = document.getElementById("meteo-station-card");
  if (!aqCardEl || !meteoCardEl) return;

  const aqCardBottom = 208;
  const aqCardHeight = aqCardEl.hidden ? 0 : aqCardEl.offsetHeight;
  const gap = aqCardHeight ? 10 : 0;
  meteoCardEl.style.bottom = (aqCardBottom + aqCardHeight + gap) + "px";
}

/* Nudge markers apart (in fixed screen pixels, not geo-degrees, so the
   separation holds at any zoom level) when a meteo station and an air
   quality station sit almost on top of each other. */
var STATION_DECLUTTER_METERS = 250;
var STATION_DECLUTTER_PX = 8;

function metersBetween(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const meanLat = (lat1 + lat2) / 2 * Math.PI / 180;
  const x = dLon * Math.cos(meanLat);
  const y = dLat;
  return R * Math.sqrt(x * x + y * y);
}

function computeStationDeclutterShifts(aqStations, meteoStations) {
  const aqShifts = new Map();
  const meteoShifts = new Map();

  (meteoStations || []).forEach(meteo => {
    if (typeof meteo.lat !== "number" || typeof meteo.lon !== "number") return;

    let nearestAq = null, nearestDist = Infinity;
    (aqStations || []).forEach(aq => {
      if (typeof aq.lat !== "number" || typeof aq.lon !== "number") return;
      const dist = metersBetween(meteo.lat, meteo.lon, aq.lat, aq.lon);
      if (dist < nearestDist) { nearestDist = dist; nearestAq = aq; }
    });

    if (nearestAq && nearestDist < STATION_DECLUTTER_METERS) {
      meteoShifts.set(meteo.name, STATION_DECLUTTER_PX);
      aqShifts.set(nearestAq.name, -STATION_DECLUTTER_PX);
    }
  });

  return { aqShifts, meteoShifts };
}

/* ═══════════════════════════════════════════════════
   RENDER BUILDINGS
═══════════════════════════════════════════════════ */
function isFeatureRenovated(p) {
  return !!(p.renovation && String(p.renovation).trim());
}

function shouldRenderFeature(feature) {
  const p = feature && feature.properties;
  if (!p) return false;
  const energyClass = getFeatureEnergyClass(feature);
  if (!energyClass || !activeClasses.has(energyClass)) return false;
  if (!activeRegions.has(p.__region)) return false;

  if (activeYearMin !== null || activeYearMax !== null) {
    const year = parseInt(p.manufacture_year, 10);
    if (!isFinite(year)) return false;
    if (activeYearMin !== null && year < activeYearMin) return false;
    if (activeYearMax !== null && year > activeYearMax) return false;
  }

  if (activeRenovationFilter === "renovated" && !isFeatureRenovated(p)) return false;
  if (activeRenovationFilter === "unrenovated" && isFeatureRenovated(p)) return false;

  if (cityFilterHighlightActive && !featureMatchesCityFilter(feature)) return false;

  return true;
}

function renderBuildings(fitToBoundsAfterRender) {
  if (!allData) return;
  if (buildingsLayer) map.removeLayer(buildingsLayer);

  renderToken += 1;
  const token = renderToken;

  buildingsLayer = L.geoJSON(null, {
    renderer: geoJsonRenderer,
    filter: shouldRenderFeature,
    style: style,
    onEachFeature: onEachFeature
  }).addTo(map);

  const features = Array.isArray(allData.features) ? allData.features : [];
  let i = 0;
  let addedCount = 0;
  let skippedCount = 0;
  console.log("[map] Rendering features:", features.length);

  function addChunk() {
    if (token !== renderToken) return;

    const end = Math.min(i + RENDER_CHUNK_SIZE, features.length);
    for (; i < end; i++) {
      try {
        buildingsLayer.addData(features[i]);
        addedCount += 1;
      } catch (err) {
        skippedCount += 1;
        if (skippedCount <= 5) {
          console.warn("[map] Skipping malformed feature at index", i, err);
        }
      }
    }

    if (i < features.length) {
      if (i % (RENDER_CHUNK_SIZE * 10) === 0) {
        console.log("[map] Rendered", i, "of", features.length);
      }
      setTimeout(addChunk, 0);
      return;
    }

    console.log("[map] Rendering complete. Total:", features.length, "Added:", addedCount, "Skipped:", skippedCount);
    updateStatsPanel();
    if (fitToBoundsAfterRender && buildingsLayer) {
      const b = buildingsLayer.getBounds();
      if (b.isValid()) {
        map.fitBounds(b);
        homeBounds = b;
      }
    }
  }

  addChunk();
}

/* Add/remove only the buildings whose combined class+region visibility
   actually changed, leaving every other building's layer untouched. */
function updateBuildingsFilter() {
  if (!buildingsLayer || !allData) return;

  const layerByFeature = new Map();
  buildingsLayer.eachLayer(function (layer) {
    layerByFeature.set(layer.feature, layer);
  });

  const features = Array.isArray(allData.features) ? allData.features : [];
  features.forEach(feature => {
    const shouldShow = shouldRenderFeature(feature);
    const existingLayer = layerByFeature.get(feature);
    if (shouldShow && !existingLayer) {
      try {
        buildingsLayer.addData(feature);
      } catch (err) {
        console.warn("[map] Skipping malformed feature", err);
      }
    } else if (!shouldShow && existingLayer) {
      buildingsLayer.removeLayer(existingLayer);
    }
  });

  updateStatsPanel();
}

/* ═══════════════════════════════════════════════════
   LEGEND + FILTER
═══════════════════════════════════════════════════ */
var legend = L.control({ position: "topright" });

legend.onAdd = function () {
  var div = L.DomUtil.create("div", "energy-legend");

  div.innerHTML = `
    <div class="legend-head">
      <div>
        <div class="legend-title">Energy Class Filter</div>
      </div>
      <button class="legend-help-btn" type="button" data-action="help" title="Class definition help">?</button>
      <button type="button" class="legend-help-btn legend-collapse-btn" data-action="collapse-panel" title="Collapse" aria-label="Collapse Energy Class panel">▾</button>
      <div class="legend-help-panel" id="legend-help-panel">
        <p class="legend-help-title">Definition of energy classes for residential buildings in Latvia.</p>
        <table class="legend-table">
          <thead>
            <tr>
              <th rowspan="3">Building energy efficiency class</th>
              <th colspan="3">Energy consumption for heating (kWh/m2)</th>
            </tr>
            <tr>
              <th colspan="3">Heated area (m2)</th>
            </tr>
            <tr>
              <th>50 to 120</th>
              <th>120 to 250</th>
              <th>over 250</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>A+</td><td>&le; 35</td><td>&le; 35</td><td>&le; 30</td></tr>
            <tr><td>A</td><td>&le; 60</td><td>&le; 50</td><td>&le; 40</td></tr>
            <tr><td>B</td><td>&le; 75</td><td>&le; 65</td><td>&le; 60</td></tr>
            <tr><td>C</td><td>&le; 95</td><td>&le; 90</td><td>&le; 80</td></tr>
            <tr><td>D</td><td>&le; 150</td><td>&le; 130</td><td>&le; 100</td></tr>
            <tr><td>E</td><td>&le; 180</td><td>&le; 150</td><td>&le; 125</td></tr>
            <tr><td>F</td><td>over 180</td><td>over 150</td><td>over 125</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="legend-actions">
      <button class="legend-btn" data-action="all">Select all</button>
      <button class="legend-btn" data-action="none">Clear all</button>
    </div>
    <div class="legend-actions" style="margin-top:-2px;">
      <button class="legend-btn" data-action="chart" style="grid-column:1 / span 2;">Class distribution chart</button>
    </div>
    <div class="legend-items">
      ${["A+","A","B","C","D","E","F"].map(cls => `
        <div class="legend-item" data-cls="${cls}" role="button" aria-label="Toggle class ${cls}">
          <span class="legend-swatch" style="background:${getEnergyColor(cls)}"></span>
          <span class="legend-class">${cls}</span>
          <span class="legend-check checked" aria-hidden="true">✓</span>
        </div>
      `).join("")}
    </div>
    <div class="legend-chart-panel open" id="legend-chart-panel">
      <div class="legend-chart-title">Visible buildings by class</div>
      <div id="legend-bar" class="bottom-sheet-bar" aria-hidden="true"></div>
      <span id="legend-bar-count" class="bottom-sheet-count">0 buildings</span>
    </div>
  `;

  const helpPanel = div.querySelector("#legend-help-panel");
  const chartPanel = div.querySelector("#legend-chart-panel");

  function updateLegendUI() {
    div.querySelectorAll(".legend-item").forEach(row => {
      const cls = row.getAttribute("data-cls");
      const on  = activeClasses.has(cls);
      row.classList.toggle("off", !on);
      row.querySelector(".legend-check").classList.toggle("checked", on);
    });
  }

  updateLegendUI();
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);

  div.addEventListener("click", function (e) {
    const actionBtn = e.target.closest("[data-action]");
    if (actionBtn) {
      const action = actionBtn.getAttribute("data-action");
      if (action === "help") {
        helpPanel.classList.toggle("open");
        return;
      }
      if (action === "collapse-panel") {
        const collapsed = div.classList.toggle("collapsed");
        actionBtn.textContent = collapsed ? "▸" : "▾";
        actionBtn.title = collapsed ? "Expand" : "Collapse";
        actionBtn.setAttribute("aria-label", collapsed ? "Expand Energy Class panel" : "Collapse Energy Class panel");
        syncChipActiveState("energy-class", collapsed);
        return;
      }
      if (action === "chart") {
        chartPanel.classList.toggle("open");
        updateStatsPanel();
        return;
      }
      if (action === "all")  activeClasses = new Set(CLASS_ORDER);
      if (action === "none") activeClasses = new Set();
      updateLegendUI();
      updateBuildingsFilter();
      return;
    }
    const row = e.target.closest("[data-cls]");
    if (!row) return;
    const cls = row.getAttribute("data-cls");
    if (activeClasses.has(cls)) activeClasses.delete(cls);
    else activeClasses.add(cls);
    updateLegendUI();
    updateBuildingsFilter();
  });

  return div;
};

/* ═══════════════════════════════════════════════════
   YEAR / RENOVATION FILTER
═══════════════════════════════════════════════════ */
var yearFilterLegend = L.control({ position: "topright" });

yearFilterLegend.onAdd = function () {
  var div = L.DomUtil.create("div", "energy-legend year-filter-control");

  div.innerHTML = `
    <div class="legend-head">
      <div class="legend-title">Year Filter</div>
      <button type="button" class="legend-help-btn legend-collapse-btn" data-action="collapse-panel" title="Collapse" aria-label="Collapse Year Filter panel">▾</button>
    </div>
    <div class="year-filter-block">
      <div class="year-filter-label">Construction year</div>
      <div class="year-filter-range">
        <input type="number" class="year-filter-input" id="year-filter-min" placeholder="Min" inputmode="numeric">
        <span class="year-filter-dash">–</span>
        <input type="number" class="year-filter-input" id="year-filter-max" placeholder="Max" inputmode="numeric">
      </div>
    </div>
    <div class="year-filter-block">
      <div class="year-filter-label">Renovation</div>
      <div class="year-filter-options">
        <label class="year-filter-option">
          <input type="radio" name="renovation-filter" value="all" checked>
          <span>All buildings</span>
        </label>
        <label class="year-filter-option">
          <input type="radio" name="renovation-filter" value="renovated">
          <span>Renovated only</span>
        </label>
        <label class="year-filter-option">
          <input type="radio" name="renovation-filter" value="unrenovated">
          <span>Not renovated</span>
        </label>
      </div>
    </div>
    <div class="legend-actions" style="margin-top:8px;">
      <button class="legend-btn" data-action="reset-year" style="grid-column:1 / span 2;">Reset</button>
    </div>
  `;

  const minInput = div.querySelector("#year-filter-min");
  const maxInput = div.querySelector("#year-filter-max");
  const radios = div.querySelectorAll('input[name="renovation-filter"]');

  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);

  minInput.addEventListener("input", function () {
    const v = minInput.value.trim();
    activeYearMin = v === "" ? null : parseInt(v, 10);
    updateBuildingsFilter();
  });

  maxInput.addEventListener("input", function () {
    const v = maxInput.value.trim();
    activeYearMax = v === "" ? null : parseInt(v, 10);
    updateBuildingsFilter();
  });

  radios.forEach(radio => {
    radio.addEventListener("change", function () {
      if (radio.checked) {
        activeRenovationFilter = radio.value;
        updateBuildingsFilter();
      }
    });
  });

  div.addEventListener("click", function (e) {
    const collapseBtn = e.target.closest("[data-action='collapse-panel']");
    if (collapseBtn) {
      const collapsed = div.classList.toggle("collapsed");
      collapseBtn.textContent = collapsed ? "▸" : "▾";
      collapseBtn.setAttribute("aria-label", collapsed ? "Expand Year Filter panel" : "Collapse Year Filter panel");
      syncChipActiveState("year", collapsed);
      return;
    }
    if (!e.target.closest('[data-action="reset-year"]')) return;
    minInput.value = "";
    maxInput.value = "";
    activeYearMin = null;
    activeYearMax = null;
    activeRenovationFilter = "all";
    div.querySelector('input[name="renovation-filter"][value="all"]').checked = true;
    updateBuildingsFilter();
  });

  return div;
};

/* ═══════════════════════════════════════════════════
   REGION FILTER
═══════════════════════════════════════════════════ */
var regionLegendItemsEl = null;
var regionBordersLayer = L.layerGroup();
var regionBordersVisible = false;

function updateRegionLegendUI() {
  if (!regionLegendItemsEl) return;
  regionLegendItemsEl.querySelectorAll("[data-region]").forEach(row => {
    const name = row.getAttribute("data-region");
    const on = activeRegions.has(name);
    row.classList.toggle("off", !on);
    row.querySelector(".legend-check").classList.toggle("checked", on);
  });
}

function getRegionColor(name) {
  const idx = REGION_ORDER.indexOf(name);
  return REGION_COLORS[(idx < 0 ? 0 : idx) % REGION_COLORS.length];
}

function renderRegionLegendItems() {
  if (!regionLegendItemsEl) return;
  regionLegendItemsEl.innerHTML = REGION_ORDER.map((name, idx) => {
    const color = REGION_COLORS[idx % REGION_COLORS.length];
    return `
      <div class="legend-item" data-region="${name}" role="button" aria-label="Toggle region ${name}">
        <span class="legend-swatch" style="background:${color}"></span>
        <span class="legend-region-name">${name}</span>
        <span class="legend-check checked" aria-hidden="true">✓</span>
      </div>
    `;
  }).join("");
  updateRegionLegendUI();
}

function buildRegionBorderLayers() {
  if (!map.getPane("regionBordersPane")) {
    const pane = map.createPane("regionBordersPane");
    pane.style.pointerEvents = "none";
    pane.style.zIndex = 450;
  }

  regionBordersLayer.clearLayers();
  regionPolygons.forEach(region => {
    const latlngs = region.ring.map(pt => [pt[1], pt[0]]);
    L.polygon(latlngs, {
      pane: "regionBordersPane",
      color: getRegionColor(region.name),
      weight: 3,
      opacity: 0.9,
      fill: false,
      interactive: false
    }).addTo(regionBordersLayer);
  });
}

function setRegionBordersVisible(visible) {
  regionBordersVisible = visible;
  if (visible) {
    if (!map.hasLayer(regionBordersLayer)) regionBordersLayer.addTo(map);
  } else if (map.hasLayer(regionBordersLayer)) {
    map.removeLayer(regionBordersLayer);
  }
}

var regionLegend = L.control({ position: "topleft" });

regionLegend.onAdd = function () {
  var div = L.DomUtil.create("div", "energy-legend region-filter-control");

  div.innerHTML = `
    <div class="legend-head">
      <div class="legend-title">Region Filter</div>
      <button type="button" class="legend-help-btn legend-collapse-btn" data-action="collapse-panel" title="Collapse" aria-label="Collapse Region Filter panel">▾</button>
    </div>
    <div class="legend-toggle-row">
      <span class="legend-toggle-label">Show region borders</span>
      <button type="button" class="legend-switch" data-region-borders-toggle role="switch" aria-checked="false" aria-label="Toggle region border lines">
        <span class="legend-switch-thumb"></span>
      </button>
    </div>
    <div class="legend-actions">
      <button class="legend-btn" data-region-action="all">Select all</button>
      <button class="legend-btn" data-region-action="none">Clear all</button>
    </div>
    <div class="legend-items" id="region-legend-items"></div>
  `;

  regionLegendItemsEl = div.querySelector("#region-legend-items");
  const bordersToggleEl = div.querySelector("[data-region-borders-toggle]");

  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);

  div.addEventListener("click", function (e) {
    const collapseBtn = e.target.closest("[data-action='collapse-panel']");
    if (collapseBtn) {
      const collapsed = div.classList.toggle("collapsed");
      collapseBtn.textContent = collapsed ? "▸" : "▾";
      collapseBtn.title = collapsed ? "Expand" : "Collapse";
      collapseBtn.setAttribute("aria-label", collapsed ? "Expand Region Filter panel" : "Collapse Region Filter panel");
      syncChipActiveState("region", collapsed);
      return;
    }
    if (e.target.closest("[data-region-borders-toggle]")) {
      setRegionBordersVisible(!regionBordersVisible);
      bordersToggleEl.classList.toggle("on", regionBordersVisible);
      bordersToggleEl.setAttribute("aria-checked", String(regionBordersVisible));
      return;
    }
    const actionBtn = e.target.closest("[data-region-action]");
    if (actionBtn) {
      const action = actionBtn.getAttribute("data-region-action");
      activeRegions = action === "all" ? new Set(REGION_ORDER) : new Set();
      updateRegionLegendUI();
      updateBuildingsFilter();
      return;
    }
    const row = e.target.closest("[data-region]");
    if (!row) return;
    const name = row.getAttribute("data-region");
    if (activeRegions.has(name)) activeRegions.delete(name);
    else activeRegions.add(name);
    updateRegionLegendUI();
    updateBuildingsFilter();
  });

  renderRegionLegendItems();
  return div;
};

/* ═══════════════════════════════════════════════════
   CITY-SCALE OVERVIEW (multi-criteria explorer)
═══════════════════════════════════════════════════ */
function rangeFilterMatches(rf, value) {
  if (!rf || rf.mode === "any") return true;
  if (value === null || value === undefined || !isFinite(value)) return false;
  if (rf.mode === "below") return rf.value1 === null ? true : value < rf.value1;
  if (rf.mode === "above") return rf.value1 === null ? true : value > rf.value1;
  if (rf.mode === "between") {
    if (rf.value1 !== null && value < rf.value1) return false;
    if (rf.value2 !== null && value > rf.value2) return false;
    return true;
  }
  return true;
}

function computeAnnualStats(p) {
  const tsEntries = Object.entries(p.heat_consumption_timeseries || {})
    .filter(([k]) => /^\d{4}-\d{2}$/.test(String(k)))
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  const last12 = tsEntries.slice(-12).map(([, v]) => parseNum(v));
  const mwh = last12.reduce((sum, v) => sum + (v || 0), 0);
  const refArea = parseNum(p.reference_area_m2);
  const perArea = (refArea && refArea > 0 && last12.length) ? (mwh * 1000) / refArea : null;
  return { mwh, perArea };
}

var cityBuildingStatsByFeature = new Map();
var cityBuildingStatsSorted = [];
var cityTotalMWh = 0;

function buildCityBuildingStats() {
  cityBuildingStatsByFeature = new Map();
  cityBuildingStatsSorted = [];
  cityTotalMWh = 0;

  const features = (allData && Array.isArray(allData.features)) ? allData.features : [];
  features.forEach(feature => {
    const stats = computeAnnualStats(feature.properties || {});
    cityBuildingStatsByFeature.set(feature, stats);
    cityTotalMWh += stats.mwh;
    if (stats.perArea !== null) cityBuildingStatsSorted.push(stats.perArea);
  });
  cityBuildingStatsSorted.sort((a, b) => b - a);
}

function getTopPercentThreshold(pct) {
  if (!cityBuildingStatsSorted.length || !pct || pct <= 0) return null;
  const count = Math.max(1, Math.min(cityBuildingStatsSorted.length, Math.ceil(cityBuildingStatsSorted.length * (pct / 100))));
  return cityBuildingStatsSorted[count - 1];
}

function makeRangeFilterState() {
  return { mode: "any", value1: null, value2: null };
}

function makeDefaultCityFilter() {
  return {
    year: makeRangeFilterState(),
    renovated: "any",
    renovationYear: makeRangeFilterState(),
    classMin: "",
    classMax: "",
    totalArea: makeRangeFilterState(),
    groundFloors: makeRangeFilterState(),
    undergroundFloors: "any",
    regions: REGION_ORDER.length ? new Set(REGION_ORDER) : null,
    heatIndicator: makeRangeFilterState(),
    topPercentEnabled: false,
    topPercentValue: 10
  };
}

var cityFilter = makeDefaultCityFilter();
var cityFilterHighlightActive = false;
var cityOverviewPanelEl = null;

function featureMatchesCityFilter(feature) {
  const p = feature && feature.properties;
  if (!p) return false;

  const year = parseInt(p.manufacture_year, 10);
  if (!rangeFilterMatches(cityFilter.year, isFinite(year) ? year : null)) return false;

  const renovated = isFeatureRenovated(p);
  if (cityFilter.renovated === "yes" && !renovated) return false;
  if (cityFilter.renovated === "no" && renovated) return false;
  if (cityFilter.renovated === "yes") {
    const renYear = parseInt(p.renovation, 10);
    if (!rangeFilterMatches(cityFilter.renovationYear, isFinite(renYear) ? renYear : null)) return false;
  }

  if (cityFilter.classMin || cityFilter.classMax) {
    const cls = getFeatureEnergyClass(feature);
    if (!cls) return false;
    const idx = CLASS_ORDER.indexOf(cls);
    if (cityFilter.classMin && idx < CLASS_ORDER.indexOf(cityFilter.classMin)) return false;
    if (cityFilter.classMax && idx > CLASS_ORDER.indexOf(cityFilter.classMax)) return false;
  }

  const totalArea = parseNum(bd(p, "BuildingOrPremiseGroupExplicationData.TotalArea"));
  if (!rangeFilterMatches(cityFilter.totalArea, totalArea)) return false;

  const groundFloors = parseNum(bd(p, "BuildingBasicData.BuildingGroundFloors"));
  if (!rangeFilterMatches(cityFilter.groundFloors, groundFloors)) return false;

  const undergroundFloors = parseNum(bd(p, "BuildingBasicData.BuildingUndergroundFloors"));
  const hasUnderground = !!(undergroundFloors && undergroundFloors > 0);
  if (cityFilter.undergroundFloors === "yes" && !hasUnderground) return false;
  if (cityFilter.undergroundFloors === "no" && hasUnderground) return false;

  if (cityFilter.regions && cityFilter.regions.size && cityFilter.regions.size < REGION_ORDER.length) {
    if (!cityFilter.regions.has(p.__region)) return false;
  }

  const heatIndicator = parseHeatingIndicator(p.heating_indicator);
  if (!rangeFilterMatches(cityFilter.heatIndicator, heatIndicator)) return false;

  if (cityFilter.topPercentEnabled) {
    const stats = cityBuildingStatsByFeature.get(feature);
    const perArea = stats ? stats.perArea : null;
    const threshold = getTopPercentThreshold(cityFilter.topPercentValue);
    if (threshold === null || perArea === null || perArea < threshold) return false;
  }

  return true;
}

function computeCityFilterResults() {
  const features = (allData && Array.isArray(allData.features)) ? allData.features : [];
  let count = 0, totalArea = 0, matchedMwh = 0;
  features.forEach(feature => {
    if (!featureMatchesCityFilter(feature)) return;
    count += 1;
    const p = feature.properties || {};
    const areaVal = parseNum(bd(p, "BuildingOrPremiseGroupExplicationData.TotalArea"));
    if (areaVal) totalArea += areaVal;
    const stats = cityBuildingStatsByFeature.get(feature);
    if (stats) matchedMwh += stats.mwh;
  });
  const mwhShare = cityTotalMWh > 0 ? (matchedMwh / cityTotalMWh) * 100 : 0;
  return { count, totalArea, mwhShare };
}

function exportCityFilterResults() {
  const features = (allData && Array.isArray(allData.features)) ? allData.features : [];
  const matched = features.filter(featureMatchesCityFilter);
  const results = computeCityFilterResults();
  const payload = {
    generated_at: new Date().toISOString(),
    buildings_matched: results.count,
    total_area_m2: results.totalArea,
    share_of_citywide_last_year_heat_consumption_pct: Number(results.mwhShare.toFixed(2)),
    buildings: matched.map(buildBuildingExportPayload)
  };
  downloadJSON(`city-scale-overview-export-${matched.length}-buildings.json`, payload);
}

function renderCfRegionOptions() {
  if (!cityOverviewPanelEl) return;
  const listEl = cityOverviewPanelEl.querySelector("#cf-region-list");
  if (!listEl) return;
  if (!cityFilter.regions) cityFilter.regions = new Set(REGION_ORDER);
  listEl.innerHTML = REGION_ORDER.map(name => `
    <button type="button" class="cf-chip${cityFilter.regions.has(name) ? " active" : ""}" data-cf-region="${name}">${name}</button>
  `).join("");
}

function updateCityFilterResultsUI() {
  if (!cityOverviewPanelEl) return;
  const results = computeCityFilterResults();
  const countEl = cityOverviewPanelEl.querySelector("#cf-results-count");
  const areaEl = cityOverviewPanelEl.querySelector("#cf-results-area");
  const shareEl = cityOverviewPanelEl.querySelector("#cf-results-share");
  if (countEl) countEl.textContent = results.count.toLocaleString();
  if (areaEl) areaEl.textContent = results.totalArea ? `${Math.round(results.totalArea).toLocaleString()} m²` : "-";
  if (shareEl) shareEl.textContent = `${results.mwhShare.toFixed(1)}%`;
}

var CF_RANGE_MODES = [
  { value: "any", label: "Any" },
  { value: "below", label: "Below" },
  { value: "above", label: "Above" },
  { value: "between", label: "Between" }
];

function cfRangeRowHTML(key, label) {
  const segButtons = CF_RANGE_MODES.map(opt => `
    <button type="button" class="cf-seg-btn${opt.value === "any" ? " active" : ""}" data-cf-mode-btn="${key}" data-cf-mode-value="${opt.value}">${opt.label}</button>
  `).join("");

  return `
    <div class="cf-row">
      <div class="cf-row-label">${label}</div>
      <div class="cf-row-inline">
        <div class="cf-seg-group" data-cf-seg-group="${key}">${segButtons}</div>
        <div class="cf-range-inputs" data-cf-inputs="${key}">
          <input type="number" class="cf-input" data-cf-value1="${key}" placeholder="Value" hidden>
          <span class="cf-dash" data-cf-dash="${key}" hidden>–</span>
          <input type="number" class="cf-input" data-cf-value2="${key}" placeholder="Max" hidden>
        </div>
      </div>
    </div>
  `;
}

/* "Comparison with similar buildings" filter — a single meter reusing the
   building popup's track/mid-line/point/chip classes and colors, same help
   button+explainer. Unlike the popup's single static dot, this is a dual-
   handle range control (two overlaid invisible <input type="range">s, same
   technique as the energy-class slider): "Below"/"Above" show one handle
   and reveal the in-filter side of the track; "Between" shows both handles
   and reveals the segment between them; "Any" shows no handles and the
   whole track is faded low-opacity, matching the other faded/disabled rows. */
function cfIndicatorRowHTML() {
  const segButtons = CF_RANGE_MODES.map(opt => `
    <button type="button" class="cf-seg-btn${opt.value === "any" ? " active" : ""}" data-cf-mode-btn="heatIndicator" data-cf-mode-value="${opt.value}">${opt.label}</button>
  `).join("");

  return `
    <div class="cf-row">
      <div class="cf-row-label cf-row-label-help">
        Comparison with similar buildings
        <button type="button" class="indicator-help-btn cf-row-help-btn" aria-label="Explain comparison indicator" onclick="event.stopPropagation(); this.closest('.cf-row-label').classList.toggle('show-help');">?</button>
        <div class="indicator-help">
          This value shows how a building's heating consumption compares to the average of similar buildings (i.e. those with approximately the same area and period of construction).<br>
          - +15% -&gt; uses 15% more heat energy than similar buildings<br>
          - -20% -&gt; uses 20% less heat energy than similar buildings<br>
          - 0% -&gt; right at the average
        </div>
      </div>
      <div class="cf-seg-group" data-cf-seg-group="heatIndicator">${segButtons}</div>
      <div class="panel-card indicator-card neutral cf-indicator-card" id="cf-indicator-card">
        <div class="indicator-meter">
          <div class="indicator-track" id="cf-indicator-track">
            <div class="indicator-mid"></div>
            <div class="cf-indicator-mask cf-indicator-mask-left" id="cf-indicator-mask-left"></div>
            <div class="cf-indicator-mask cf-indicator-mask-right" id="cf-indicator-mask-right"></div>
          </div>
          <div class="indicator-point-wrap" id="cf-indicator-point-wrap-1" style="left:50%;">
            <div class="indicator-value-chip neutral" id="cf-indicator-chip-1">0%</div>
            <div class="indicator-point neutral" id="cf-indicator-point-1"></div>
          </div>
          <div class="indicator-point-wrap" id="cf-indicator-point-wrap-2" style="left:50%;">
            <div class="indicator-value-chip neutral" id="cf-indicator-chip-2">0%</div>
            <div class="indicator-point neutral" id="cf-indicator-point-2"></div>
          </div>
          <input type="range" class="cf-indicator-thumb" id="cf-indicator-range-1" min="-100" max="100" step="1" value="0">
          <input type="range" class="cf-indicator-thumb" id="cf-indicator-range-2" min="-100" max="100" step="1" value="0">
        </div>
        <div class="indicator-scale">
          <span>Lower</span>
          <span>Higher</span>
        </div>
      </div>
    </div>
  `;
}

function wireRangeFilterRow(panelDiv, key, onChange) {
  const segGroup = panelDiv.querySelector(`[data-cf-seg-group="${key}"]`);
  const val1 = panelDiv.querySelector(`[data-cf-value1="${key}"]`);
  const val2 = panelDiv.querySelector(`[data-cf-value2="${key}"]`);
  const dash = panelDiv.querySelector(`[data-cf-dash="${key}"]`);
  if (!segGroup || !val1 || !val2 || !dash) return;

  function syncUI() {
    const mode = cityFilter[key].mode;
    val1.hidden = mode === "any";
    val2.hidden = mode !== "between";
    dash.hidden = mode !== "between";
    val1.placeholder = mode === "between" ? "Min" : "Value";
    segGroup.querySelectorAll("[data-cf-mode-btn]").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-cf-mode-value") === mode);
    });
  }

  segGroup.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cf-mode-btn]");
    if (!btn) return;
    cityFilter[key].mode = btn.getAttribute("data-cf-mode-value");
    syncUI();
    onChange();
  });
  val1.addEventListener("input", () => {
    const v = val1.value.trim();
    cityFilter[key].value1 = v === "" ? null : parseFloat(v);
    onChange();
  });
  val2.addEventListener("input", () => {
    const v = val2.value.trim();
    cityFilter[key].value2 = v === "" ? null : parseFloat(v);
    onChange();
  });

  syncUI();
}

function resetRangeFilterRowUI(panelDiv, key) {
  const segGroup = panelDiv.querySelector(`[data-cf-seg-group="${key}"]`);
  const val1 = panelDiv.querySelector(`[data-cf-value1="${key}"]`);
  const val2 = panelDiv.querySelector(`[data-cf-value2="${key}"]`);
  const dash = panelDiv.querySelector(`[data-cf-dash="${key}"]`);
  if (!segGroup) return;
  segGroup.querySelectorAll("[data-cf-mode-btn]").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-cf-mode-value") === "any");
  });
  val1.value = "";
  val2.value = "";
  val1.hidden = true;
  val2.hidden = true;
  dash.hidden = true;
}

function applyIndicatorVisual(panelDiv, slot, value) {
  const v = computeIndicatorVisual(value);
  const pointWrap = panelDiv.querySelector(`#cf-indicator-point-wrap-${slot}`);
  const point = panelDiv.querySelector(`#cf-indicator-point-${slot}`);
  const chip = panelDiv.querySelector(`#cf-indicator-chip-${slot}`);
  if (!pointWrap || !point || !chip) return;

  pointWrap.className = `indicator-point-wrap ${v.indicatorEdgeClass}`;
  pointWrap.style.left = v.indicatorPointPos + "%";
  point.className = `indicator-point ${v.indicatorClass}`;
  chip.className = `indicator-value-chip ${v.indicatorClass}`;
  chip.textContent = v.indicatorValueText;
}

// Reveals the in-filter portion of the track (the rest stays covered by the
// two pale masks so the bright underlying gradient only shows through where
// it's actually selected): "below" reveals from the left edge to the
// handle, "above" from the handle to the right edge, "between" the segment
// spanning both handles, and "any" reveals nothing — the same fade covers
// the whole bar so "not selected" always reads identically, whether that's
// one side of the track or all of it.
function updateIndicatorMasks(panelDiv, mode, value1, value2) {
  const maskLeft = panelDiv.querySelector("#cf-indicator-mask-left");
  const maskRight = panelDiv.querySelector("#cf-indicator-mask-right");
  if (!maskLeft || !maskRight) return;

  let revealMin = 0, revealMax = 0;
  if (mode === "below") {
    revealMax = computeIndicatorVisual(value1).indicatorPointPos;
  } else if (mode === "above") {
    revealMin = computeIndicatorVisual(value1).indicatorPointPos;
    revealMax = 100;
  } else if (mode === "between") {
    const p1 = computeIndicatorVisual(value1).indicatorPointPos;
    const p2 = computeIndicatorVisual(value2).indicatorPointPos;
    revealMin = Math.min(p1, p2);
    revealMax = Math.max(p1, p2);
  }
  maskLeft.style.width = revealMin + "%";
  maskRight.style.width = (100 - revealMax) + "%";
}

function wireIndicatorRow(panelDiv, onChange) {
  const key = "heatIndicator";
  const segGroup = panelDiv.querySelector(`[data-cf-seg-group="${key}"]`);
  const card = panelDiv.querySelector("#cf-indicator-card");
  const track = panelDiv.querySelector("#cf-indicator-track");
  const range1 = panelDiv.querySelector("#cf-indicator-range-1");
  const range2 = panelDiv.querySelector("#cf-indicator-range-2");
  const wrap1 = panelDiv.querySelector("#cf-indicator-point-wrap-1");
  const wrap2 = panelDiv.querySelector("#cf-indicator-point-wrap-2");
  if (!segGroup || !card || !track || !range1 || !range2 || !wrap1 || !wrap2) return;

  function syncUI() {
    const mode = cityFilter[key].mode;
    wrap1.style.display = mode === "any" ? "none" : "";
    wrap2.style.display = mode === "between" ? "" : "none";
    range1.style.display = mode === "any" ? "none" : "";
    range2.style.display = mode === "between" ? "" : "none";
    updateIndicatorMasks(panelDiv, mode, cityFilter[key].value1 ?? 0, cityFilter[key].value2 ?? 0);
    segGroup.querySelectorAll("[data-cf-mode-btn]").forEach(btn => {
      btn.classList.toggle("active", btn.getAttribute("data-cf-mode-value") === mode);
    });
  }

  segGroup.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cf-mode-btn]");
    if (!btn) return;
    const mode = btn.getAttribute("data-cf-mode-value");
    cityFilter[key].mode = mode;
    if (mode !== "any" && cityFilter[key].value1 === null) cityFilter[key].value1 = 0;
    if (mode === "between" && cityFilter[key].value2 === null) cityFilter[key].value2 = 0;
    range1.value = String(cityFilter[key].value1 ?? 0);
    range2.value = String(cityFilter[key].value2 ?? 0);
    applyIndicatorVisual(panelDiv, 1, cityFilter[key].value1 ?? 0);
    applyIndicatorVisual(panelDiv, 2, cityFilter[key].value2 ?? 0);
    syncUI();
    onChange();
  });

  // Same collapsed-handle problem as the energy-class slider: when both
  // handles share a value in "between" mode, raise whichever input the
  // user is actually touching so it can be dragged open in that direction.
  function prioritizeIndicatorThumb(clientX) {
    if (cityFilter[key].mode !== "between") return;
    const v1 = parseInt(range1.value, 10);
    const v2 = parseInt(range2.value, 10);
    if (v1 !== v2) return;
    const rect = track.getBoundingClientRect();
    const pct = ((clientX - rect.left) / rect.width) * 100;
    const currentPct = computeIndicatorVisual(v1).indicatorPointPos;
    if (pct < currentPct) {
      range1.style.zIndex = "3";
      range2.style.zIndex = "1";
    } else {
      range2.style.zIndex = "3";
      range1.style.zIndex = "1";
    }
  }

  const meterEl = panelDiv.querySelector(".indicator-meter");
  meterEl.addEventListener("pointerdown", (e) => prioritizeIndicatorThumb(e.clientX));
  meterEl.addEventListener("touchstart", (e) => {
    if (e.touches && e.touches[0]) prioritizeIndicatorThumb(e.touches[0].clientX);
  }, { passive: true });

  range1.addEventListener("input", () => {
    let v = parseInt(range1.value, 10);
    if (cityFilter[key].mode === "between" && v > parseInt(range2.value, 10)) {
      v = parseInt(range2.value, 10);
      range1.value = String(v);
    }
    cityFilter[key].value1 = v;
    applyIndicatorVisual(panelDiv, 1, v);
    updateIndicatorMasks(panelDiv, cityFilter[key].mode, v, cityFilter[key].value2 ?? v);
    onChange();
  });
  range2.addEventListener("input", () => {
    let v = parseInt(range2.value, 10);
    if (v < parseInt(range1.value, 10)) {
      v = parseInt(range1.value, 10);
      range2.value = String(v);
    }
    cityFilter[key].value2 = v;
    applyIndicatorVisual(panelDiv, 2, v);
    updateIndicatorMasks(panelDiv, cityFilter[key].mode, cityFilter[key].value1 ?? v, v);
    onChange();
  });

  applyIndicatorVisual(panelDiv, 1, cityFilter[key].value1 ?? 0);
  applyIndicatorVisual(panelDiv, 2, cityFilter[key].value2 ?? 0);
  syncUI();
}

function resetIndicatorRowUI(panelDiv) {
  const segGroup = panelDiv.querySelector('[data-cf-seg-group="heatIndicator"]');
  const card = panelDiv.querySelector("#cf-indicator-card");
  const range1 = panelDiv.querySelector("#cf-indicator-range-1");
  const range2 = panelDiv.querySelector("#cf-indicator-range-2");
  const wrap1 = panelDiv.querySelector("#cf-indicator-point-wrap-1");
  const wrap2 = panelDiv.querySelector("#cf-indicator-point-wrap-2");
  if (!segGroup || !card || !range1 || !range2 || !wrap1 || !wrap2) return;
  segGroup.querySelectorAll("[data-cf-mode-btn]").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-cf-mode-value") === "any");
  });
  range1.value = "0";
  range2.value = "0";
  applyIndicatorVisual(panelDiv, 1, 0);
  applyIndicatorVisual(panelDiv, 2, 0);
  wrap1.style.display = "none";
  wrap2.style.display = "none";
  range1.style.display = "none";
  range2.style.display = "none";
  updateIndicatorMasks(panelDiv, "any", 0, 0);
}

/* City-scale overview has two UIs sharing one #city-overview-panel — see
   the "min-height: 701px" block in styles.css for which shows when.
   Below that height: #bottom-sheet-handle expands #city-overview-panel
   in place via a CSS max-height transition (no positioning math needed).
   At/above it: #bottom-sheet becomes `display: contents` (so it stops
   affecting layout) and the colleague's original floating button +
   JS-positioned panel take over — positionCityOverviewPanel() anchors
   the panel to the button's actual on-screen corner. The breakpoint
   value must stay in sync with styles.css by hand; there's no single
   source of truth to share it from. */
var DESKTOP_OVERVIEW_QUERY = window.matchMedia("(min-height: 701px)");
var bottomSheetEl = document.getElementById("bottom-sheet");
var bottomSheetHandle = document.getElementById("bottom-sheet-handle");
var cityOverviewToggleBtn = document.getElementById("city-overview-toggle-btn");

/* #minimap-toggle's own top edge — the tallest point of the minimap
   stack — at bottom:178px+height:22px when open, or bottom:20px+
   height:22px once collapsed (see the minimap toggle handler above).
   Kept in sync with those values by hand, same as the 701px breakpoint
   above. */
var MINIMAP_TOP_EXPANDED = 200;
var MINIMAP_TOP_COLLAPSED = 42;
var CITY_OVERVIEW_GAP = 10;

/* Keeps the City-scale Overview trigger (in either of its two forms —
   .city-overview-toggle-btn on tall viewports, .bottom-sheet on short
   ones) anchored just above the minimap, following it down when the
   minimap is collapsed to just its #minimap-toggle tab. */
function updateCityOverviewAnchor() {
  var bottom = (minimapVisible ? MINIMAP_TOP_EXPANDED : MINIMAP_TOP_COLLAPSED) + CITY_OVERVIEW_GAP + "px";
  if (cityOverviewToggleBtn) cityOverviewToggleBtn.style.bottom = bottom;
  if (bottomSheetEl) bottomSheetEl.style.bottom = bottom;
  if (bottomSheetEl && bottomSheetEl.classList.contains("expanded") && DESKTOP_OVERVIEW_QUERY.matches) {
    positionCityOverviewPanel();
  }
}

function positionCityOverviewPanel() {
  if (!cityOverviewPanelEl || !cityOverviewToggleBtn) return;
  const rect = cityOverviewToggleBtn.getBoundingClientRect();
  const margin = 16;

  // right/bottom are resolved against offsetParent — #map-viewport at this
  // breakpoint, since #bottom-sheet is `display: contents` and drops out
  // of the positioned-ancestor chain.
  const containerRect = (cityOverviewPanelEl.offsetParent || document.documentElement).getBoundingClientRect();

  cityOverviewPanelEl.style.left = "auto";
  cityOverviewPanelEl.style.top = "auto";
  cityOverviewPanelEl.style.right = Math.round(containerRect.right - rect.right) + "px";
  cityOverviewPanelEl.style.bottom = Math.round(containerRect.bottom - rect.top + 4) + "px";
  // Capped against containerRect.top (#map-viewport's own top edge), not
  // 0/the browser viewport's top — the map sits below a breadcrumb/header
  // (see the file-level comment above), so the viewport's top is usually
  // higher up than the map's, and the panel would otherwise be able to
  // grow past the top of the map into that header.
  cityOverviewPanelEl.style.maxHeight = Math.max(280, rect.top - containerRect.top - margin) + "px";
}

function toggleCityOverviewPanel() {
  if (!bottomSheetEl || !cityOverviewPanelEl) return;
  const expanding = !bottomSheetEl.classList.contains("expanded");
  const desktop = DESKTOP_OVERVIEW_QUERY.matches;

  // Apply `.expanded` first: positionCityOverviewPanel() reads
  // cityOverviewPanelEl.offsetParent, which is null while the panel is
  // still `display: none` — before `.expanded` flips it to `display:
  // block`, offsetParent falls back past #map-viewport all the way to
  // <html>, so the computed `bottom` picks up the page content below
  // the map (footer etc.) and the panel opens far above the button.
  bottomSheetEl.classList.toggle("expanded", expanding);

  if (expanding && desktop) {
    positionCityOverviewPanel();
  } else if (!desktop) {
    // Clear any leftover inline positioning from a previous desktop-mode
    // expand, so the compact mode's CSS max-height transition isn't
    // fighting a higher-specificity inline style.
    cityOverviewPanelEl.style.right = "";
    cityOverviewPanelEl.style.bottom = "";
    cityOverviewPanelEl.style.maxHeight = "";
  }

  if (bottomSheetHandle) bottomSheetHandle.setAttribute("aria-expanded", String(expanding));
  if (cityOverviewToggleBtn) {
    cityOverviewToggleBtn.classList.toggle("open", expanding);
    cityOverviewToggleBtn.setAttribute("aria-expanded", String(expanding));
  }
}

if (bottomSheetHandle) {
  bottomSheetHandle.addEventListener("click", toggleCityOverviewPanel);
}
if (cityOverviewToggleBtn) {
  cityOverviewToggleBtn.addEventListener("click", toggleCityOverviewPanel);
}

window.addEventListener("resize", function () {
  POPUP_MAX_HEIGHT = Math.max(280, map.getSize().y - POPUP_AUTOPAN_PADDING.autoPanPaddingTopLeft.y - POPUP_AUTOPAN_PADDING.autoPanPaddingBottomRight.y);
  if (bottomSheetEl && bottomSheetEl.classList.contains("expanded") && DESKTOP_OVERVIEW_QUERY.matches) positionCityOverviewPanel();
});

var CF_ICON_HIGHLIGHT = `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2"/></svg>`;

function cfSegSimpleHTML(groupAttr, options) {
  return options.map((opt, idx) => `
    <button type="button" class="cf-seg-btn${idx === 0 ? " active" : ""}" data-${groupAttr}="${opt.value}">${opt.label}</button>
  `).join("");
}

function initCityOverviewPanel() {
  const div = document.getElementById("city-overview-panel");
  if (!div) return;
  cityOverviewPanelEl = div;

  div.innerHTML = `
    <div class="cf-panel-header">
      <button class="legend-help-btn cf-panel-close" type="button" data-action="close-panel" title="Close" aria-label="Close city overview">✕</button>
      <div class="cf-panel-title">City-scale Overview</div>
      <div class="cf-panel-subtitle">Explore multi-apartment residential buildings by multiple criteria at a city level.</div>
    </div>
    <div class="cf-grid">
      <div class="cf-grid-col">
      <div class="cf-section">
        <div class="cf-section-title">Construction &amp; renovation</div>
        <div class="cf-section-card">
        <div class="cf-section-rows">
          ${cfRangeRowHTML("year", "Construction year")}
          <div class="cf-row">
            <div class="cf-row-label">Renovated</div>
            <div class="cf-seg-group" id="cf-renovated-group">
              ${cfSegSimpleHTML("cf-renovated", [
                { value: "any", label: "Any" },
                { value: "yes", label: "Renovated" },
                { value: "no", label: "Not renovated" }
              ])}
            </div>
          </div>
          <div id="cf-renovation-year-row" class="cf-row-faded">
            ${cfRangeRowHTML("renovationYear", "Renovation year")}
          </div>
        </div>
        </div>
      </div>

      <div class="cf-section cf-section-narrow">
        <div class="cf-section-title">Heat performance</div>
        <div class="cf-section-card">
        <div class="cf-section-rows">
          ${cfIndicatorRowHTML()}
          <div class="cf-row">
            <div class="cf-row-label cf-row-label-help">
              Comparison with all buildings
              <button type="button" class="indicator-help-btn cf-row-help-btn" aria-label="Explain citywide heat use ranking" onclick="event.stopPropagation(); this.closest('.cf-row-label').classList.toggle('show-help');">?</button>
              <div class="indicator-help">
                Unlike the comparison above, this doesn't account for building age or area — it just ranks heating energy used per m² of floor area (last 12 months) against every other multi-apartment residential building.<br>
                "Top 10%" = the 10% of these buildings using the <strong>most</strong> heat per m² — not the most efficient ones.
              </div>
            </div>
            <div class="cf-top-row">
              <label class="cf-checkbox-row">
                <input type="checkbox" id="cf-top-enabled">
                <span>Among the top</span>
              </label>
              <input type="number" class="cf-input cf-top-input" id="cf-top-value" value="10" min="1" max="100">
              <span class="cf-row-suffix">% most energy-intensive</span>
            </div>
          </div>
        </div>
        </div>
      </div>
      </div>

      <div class="cf-grid-col">
      <div class="cf-section">
        <div class="cf-section-title">Building profile</div>
        <div class="cf-section-card">
        <div class="cf-section-rows">
          <div class="cf-row">
            <div class="cf-row-label">Energy class</div>
            <div class="cf-class-slider">
              <div class="cf-class-track" id="cf-class-track"></div>
              <div class="cf-class-mask cf-class-mask-left" id="cf-class-mask-left"></div>
              <div class="cf-class-mask cf-class-mask-right" id="cf-class-mask-right"></div>
              <input type="range" class="cf-range-thumb" id="cf-class-min-range" min="0" max="${CLASS_ORDER.length - 1}" step="1" value="0">
              <input type="range" class="cf-range-thumb" id="cf-class-max-range" min="0" max="${CLASS_ORDER.length - 1}" step="1" value="${CLASS_ORDER.length - 1}">
              <div class="cf-class-ticks">
                ${CLASS_ORDER.map((c, i) => {
                  const pct = (i / (CLASS_ORDER.length - 1)) * 100;
                  const edgeClass = i === 0 ? " cf-class-tick-start" : (i === CLASS_ORDER.length - 1 ? " cf-class-tick-end" : "");
                  return `<span class="cf-class-tick-label${edgeClass}" style="left:${pct.toFixed(2)}%;">${c}</span>`;
                }).join("")}
              </div>
            </div>
          </div>
          ${cfRangeRowHTML("totalArea", "Total area (m²)")}
          ${cfRangeRowHTML("groundFloors", "Ground floors")}
          <div class="cf-row">
            <div class="cf-row-label">Underground floors</div>
            <div class="cf-seg-group" id="cf-underground-group">
              ${cfSegSimpleHTML("cf-underground", [
                { value: "any", label: "Any" },
                { value: "yes", label: "Has floor(s)" },
                { value: "no", label: "None" }
              ])}
            </div>
          </div>
          <div class="cf-row cf-region-row">
            <div class="cf-row-label">Region</div>
            <div class="cf-region-list" id="cf-region-list"></div>
          </div>
        </div>
        </div>
      </div>
      </div>
    </div>

    <div class="cf-reset-row">
      <button class="legend-btn cf-reset-btn" data-action="cf-reset">Reset filters</button>
    </div>

    <div class="cf-results-panel">
      <div class="cf-panel-section-label cf-row-label-help">
        Results
        <span class="cf-help-btn-wrap">
          <button type="button" class="indicator-help-btn cf-row-help-btn" aria-label="Explain results" onclick="event.stopPropagation(); this.closest('.cf-help-btn-wrap').classList.toggle('show-help');">?</button>
          <div class="indicator-help">
            These results only cover the multi-apartment residential buildings shown on this map. "City-wide" in the share below means the combined heat consumption of all these buildings — not the entire city of Riga, which also includes other building types this map doesn't cover.
          </div>
        </span>
      </div>
      <div class="cf-results">
        <div class="cf-stat-tile">
          <div class="cf-stat-value" id="cf-results-count">0</div>
          <div class="cf-stat-label">Buildings match</div>
        </div>
        <div class="cf-stat-tile">
          <div class="cf-stat-value" id="cf-results-area">-</div>
          <div class="cf-stat-label">Total area</div>
        </div>
        <div class="cf-stat-tile">
          <div class="cf-stat-value" id="cf-results-share">-</div>
          <div class="cf-stat-label">Share of city-wide last year's heat consumption</div>
        </div>
      </div>
    </div>

    <div class="cf-highlight-panel" id="cf-highlight-panel">
      <div class="cf-highlight-icon">${CF_ICON_HIGHLIGHT}</div>
      <div class="cf-highlight-text">
        <div class="cf-highlight-title">Highlight matching buildings</div>
        <div class="cf-highlight-desc">Show only these buildings on the map — everything else is hidden until you turn this off.</div>
      </div>
      <button type="button" class="legend-switch" id="cf-highlight-toggle" role="switch" aria-checked="false" aria-label="Highlight matching buildings on the map">
        <span class="legend-switch-thumb"></span>
      </button>
    </div>

    <div class="cf-actions-row">
      <button class="api-btn" disabled>Open API</button>
      <button type="button" class="export-btn" data-action="cf-export">Export data</button>
    </div>
  `;

  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);

  const renYearRow = div.querySelector("#cf-renovation-year-row");
  const renovatedGroup = div.querySelector("#cf-renovated-group");
  const undergroundGroup = div.querySelector("#cf-underground-group");
  const classMinRange = div.querySelector("#cf-class-min-range");
  const classMaxRange = div.querySelector("#cf-class-max-range");
  const classTrack = div.querySelector("#cf-class-track");
  const classMaskLeft = div.querySelector("#cf-class-mask-left");
  const classMaskRight = div.querySelector("#cf-class-mask-right");
  const topEnabledEl = div.querySelector("#cf-top-enabled");
  const topValueEl = div.querySelector("#cf-top-value");
  const highlightBtn = div.querySelector("#cf-highlight-toggle");
  const highlightPanel = div.querySelector("#cf-highlight-panel");

  function onFilterChange() {
    updateCityFilterResultsUI();
    if (cityFilterHighlightActive) updateBuildingsFilter();
  }

  function setSegActive(group, value) {
    group.querySelectorAll(".cf-seg-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.cfRenovated === value || btn.dataset.cfUnderground === value);
    });
  }

  function updateClassSliderUI() {
    const lastIdx = CLASS_ORDER.length - 1;
    const minIdx = parseInt(classMinRange.value, 10);
    const maxIdx = parseInt(classMaxRange.value, 10);
    const pctMin = (minIdx / lastIdx) * 100;
    const pctMax = (maxIdx / lastIdx) * 100;
    // Reveal half a tick-step beyond each handle so the selected class(es)
    // read as a colored segment of the track itself — with both handles
    // collapsed onto one class (pctMin === pctMax) this still shows that
    // class's full colored cell rather than a zero-width sliver.
    const halfStep = (100 / lastIdx) / 2;
    const revealMin = Math.max(0, pctMin - halfStep);
    const revealMax = Math.min(100, pctMax + halfStep);
    classMaskLeft.style.width = revealMin + "%";
    classMaskRight.style.width = (100 - revealMax) + "%";
    const isFullRange = minIdx === 0 && maxIdx === lastIdx;
    cityFilter.classMin = isFullRange ? "" : CLASS_ORDER[minIdx];
    cityFilter.classMax = isFullRange ? "" : CLASS_ORDER[maxIdx];
  }

  // When both handles sit on the same class, only the top-most native
  // range input can normally be grabbed, so the user could only ever pull
  // the range open in one direction. On pointerdown, check which side of
  // the shared position the user is touching and raise that input's
  // z-index, so dragging left pulls the min handle down and dragging right
  // pulls the max handle up — whichever the user reaches for first.
  function prioritizeClassThumb(clientX) {
    const minIdx = parseInt(classMinRange.value, 10);
    const maxIdx = parseInt(classMaxRange.value, 10);
    if (minIdx !== maxIdx) return;
    const rect = classTrack.getBoundingClientRect();
    const pct = ((clientX - rect.left) / rect.width) * 100;
    const currentPct = (minIdx / (CLASS_ORDER.length - 1)) * 100;
    if (pct < currentPct) {
      classMinRange.style.zIndex = "3";
      classMaxRange.style.zIndex = "1";
    } else {
      classMaxRange.style.zIndex = "3";
      classMinRange.style.zIndex = "1";
    }
  }

  const classSliderEl = div.querySelector(".cf-class-slider");
  classSliderEl.addEventListener("pointerdown", (e) => prioritizeClassThumb(e.clientX));
  classSliderEl.addEventListener("touchstart", (e) => {
    if (e.touches && e.touches[0]) prioritizeClassThumb(e.touches[0].clientX);
  }, { passive: true });

  classTrack.style.background = `linear-gradient(90deg, ${CLASS_ORDER.map((c, i) => `${getEnergyColor(c)} ${(i / (CLASS_ORDER.length - 1) * 100).toFixed(2)}%`).join(", ")})`;

  ["year", "totalArea", "groundFloors", "renovationYear"].forEach(key => {
    wireRangeFilterRow(div, key, onFilterChange);
  });
  wireIndicatorRow(div, onFilterChange);

  renovatedGroup.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cf-renovated]");
    if (!btn) return;
    cityFilter.renovated = btn.dataset.cfRenovated;
    setSegActive(renovatedGroup, cityFilter.renovated);
    renYearRow.classList.toggle("cf-row-faded", cityFilter.renovated !== "yes");
    onFilterChange();
  });

  undergroundGroup.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cf-underground]");
    if (!btn) return;
    cityFilter.undergroundFloors = btn.dataset.cfUnderground;
    setSegActive(undergroundGroup, cityFilter.undergroundFloors);
    onFilterChange();
  });

  classMinRange.addEventListener("input", () => {
    if (parseInt(classMinRange.value, 10) > parseInt(classMaxRange.value, 10)) {
      classMinRange.value = classMaxRange.value;
    }
    updateClassSliderUI();
    onFilterChange();
  });

  classMaxRange.addEventListener("input", () => {
    if (parseInt(classMaxRange.value, 10) < parseInt(classMinRange.value, 10)) {
      classMaxRange.value = classMinRange.value;
    }
    updateClassSliderUI();
    onFilterChange();
  });

  div.addEventListener("change", function (e) {
    if (e.target === topEnabledEl) { cityFilter.topPercentEnabled = topEnabledEl.checked; onFilterChange(); return; }
  });

  topValueEl.addEventListener("input", () => {
    const v = parseFloat(topValueEl.value);
    cityFilter.topPercentValue = isFinite(v) ? v : null;
    onFilterChange();
  });

  highlightBtn.addEventListener("click", () => {
    cityFilterHighlightActive = !cityFilterHighlightActive;
    highlightBtn.classList.toggle("on", cityFilterHighlightActive);
    highlightBtn.setAttribute("aria-checked", String(cityFilterHighlightActive));
    if (highlightPanel) highlightPanel.classList.toggle("active", cityFilterHighlightActive);
    updateBuildingsFilter();
  });

  div.addEventListener("click", function (e) {
    if (e.target.closest('[data-action="close-panel"]')) {
      toggleCityOverviewPanel();
      return;
    }
    const regionChip = e.target.closest("[data-cf-region]");
    if (regionChip) {
      const name = regionChip.getAttribute("data-cf-region");
      if (cityFilter.regions.has(name)) cityFilter.regions.delete(name);
      else cityFilter.regions.add(name);
      regionChip.classList.toggle("active", cityFilter.regions.has(name));
      onFilterChange();
      return;
    }
    if (e.target.closest('[data-action="cf-reset"]')) {
      cityFilter = makeDefaultCityFilter();
      ["year", "totalArea", "groundFloors", "renovationYear"].forEach(key => {
        resetRangeFilterRowUI(div, key);
      });
      resetIndicatorRowUI(div);
      renYearRow.classList.add("cf-row-faded");
      setSegActive(renovatedGroup, "any");
      setSegActive(undergroundGroup, "any");
      classMinRange.value = "0";
      classMaxRange.value = String(CLASS_ORDER.length - 1);
      updateClassSliderUI();
      topEnabledEl.checked = false;
      topValueEl.value = "10";
      renderCfRegionOptions();
      updateCityFilterResultsUI();
      if (cityFilterHighlightActive) updateBuildingsFilter();
      return;
    }
    if (e.target.closest('[data-action="cf-export"]')) {
      exportCityFilterResults();
      return;
    }
  });

  updateClassSliderUI();
  renderCfRegionOptions();
  updateCityFilterResultsUI();
}

setupSearchControl();
legend.addTo(map);
yearFilterLegend.addTo(map);
regionLegend.addTo(map);
initCityOverviewPanel();

/* ── Filter chips (Region / Energy class / Year) ──────────────────────
   These three Leaflet controls live in one shared dropdown below a row
   of chips instead of stacked corner panels, on every screen size — only
   one open at a time. Each control's own div — with all its existing
   listeners and its own collapse button — is reparented as-is; nothing
   about its content is duplicated or rebuilt. */
function setPanelCollapsed(panelEl, collapsed, collapseLabel, expandLabel) {
  panelEl.classList.toggle("collapsed", collapsed);
  var btn = panelEl.querySelector(".legend-collapse-btn");
  if (btn) {
    btn.textContent = collapsed ? "▸" : "▾";
    btn.title = collapsed ? "Expand" : "Collapse";
    btn.setAttribute("aria-label", collapsed ? expandLabel : collapseLabel);
  }
}

var CHIP_FILTERS = [
  { key: "region", label: "Region", control: regionLegend },
  { key: "energy-class", label: "Energy class", control: legend },
  { key: "year", label: "Year", control: yearFilterLegend }
];

function initFilterChips() {
  var dropdown = document.getElementById("filter-chip-dropdown");
  if (!dropdown) return;

  CHIP_FILTERS.forEach(function (f) {
    var el = f.control.getContainer && f.control.getContainer();
    if (!el) return;
    dropdown.appendChild(el);
    setPanelCollapsed(el, true, "Collapse " + f.label, "Expand " + f.label);
  });
}

document.querySelectorAll(".filter-chip").forEach(function (chipBtn) {
  chipBtn.addEventListener("click", function () {
    var key = chipBtn.getAttribute("data-chip");
    var target = CHIP_FILTERS.find(function (f) { return f.key === key; });
    if (!target) return;
    var targetEl = target.control.getContainer();
    if (!targetEl) return;
    var opening = targetEl.classList.contains("collapsed");

    CHIP_FILTERS.forEach(function (f) {
      var el = f.control.getContainer();
      if (!el) return;
      var shouldOpen = opening && f.key === key;
      setPanelCollapsed(el, !shouldOpen, "Collapse " + f.label, "Expand " + f.label);
    });

    document.querySelectorAll(".filter-chip").forEach(function (btn) {
      var isActive = opening && btn === chipBtn;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-expanded", String(isActive));
    });
  });
});

initFilterChips();

map.on("moveend zoomend", updateStatsPanel);

/* ═══════════════════════════════════════════════════
   LOAD GEOJSON + REGION BOUNDARIES
═══════════════════════════════════════════════════ */
Promise.all([
  fetch(DATA_BASE_URL + "DT_data.json?v=" + Date.now())
    .then(r => r.text())
    .then(text => {
      // Replace NaN with null (invalid JSON fix)
      const cleanedText = text.replace(/:\s*NaN\b/g, ': null');
      return JSON.parse(cleanedText);
    }),
  fetch(encodeURI(DATA_BASE_URL + "Borders of Riga suburbs.csv") + "?v=" + Date.now())
    .then(r => r.text())
    .catch(err => {
      console.error("[map] Failed to load region boundaries:", err);
      return "";
    }),
  loadAirQualityStations()
    .catch(err => {
      console.error("[map] Failed to load air quality data:", err);
      return [];
    }),
  loadMeteoStations()
    .catch(err => {
      console.error("[map] Failed to load meteo stations:", err);
      return [];
    })
])
  .then(([data, regionsCsvText, aqStations, meteoStations]) => {
    console.log("[map] Loaded GeoJSON features:", Array.isArray(data.features) ? data.features.length : 0);
    allData = data;

    regionPolygons = parseRegionsCsv(regionsCsvText);
    REGION_ORDER = regionPolygons.map(r => r.name);
    activeRegions = new Set(REGION_ORDER);
    assignFeatureRegions(Array.isArray(data.features) ? data.features : []);
    renderRegionLegendItems();
    buildRegionBorderLayers();

    buildCityBuildingStats();
    cityFilter.regions = new Set(REGION_ORDER);
    renderCfRegionOptions();
    updateCityFilterResultsUI();

    buildSearchIndex(Array.isArray(data.features) ? data.features : []);
    renderBuildings(true);

    const { aqShifts, meteoShifts } = computeStationDeclutterShifts(aqStations, meteoStations);

    console.log("[map] Loaded air quality stations:", aqStations.length);
    renderAirQualityStations(aqStations, aqShifts);

    console.log("[map] Loaded meteo stations:", meteoStations.length);
    renderMeteoStations(meteoStations, meteoShifts);
  })
  .catch(err => console.error(err));

/* Initial sync after map is ready */
map.whenReady(function () {
  setTimeout(syncMiniMap, 100);
});

}());
