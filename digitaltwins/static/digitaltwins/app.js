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

function normalizeEnergyClass(value) {
  if (typeof value !== "string") return null;
  var cls = value.trim().toUpperCase();
  return CLASS_SET.has(cls) ? cls : null;
}

function getFeatureEnergyClass(feature) {
  if (!feature || !feature.properties) return null;
  return normalizeEnergyClass(feature.properties.energy_class);
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
   MINI MAP  (second Leaflet instance, read-only tiles)
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

function donutChartSVG(counts, total) {
  const size = 126;
  const cx = 63, cy = 63, r = 42;
  const strokeW = 14;
  const c = 2 * Math.PI * r;

  if (!total) {
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#e8eef5" stroke-width="${strokeW}"/>
        <text x="${cx}" y="${cy + 3}" text-anchor="middle" font-size="11" fill="#71839c">No data</text>
      </svg>
    `;
  }

  let acc = 0;
  let arcs = "";
  CLASS_ORDER.forEach(cls => {
    const val = counts[cls] || 0;
    if (!val) return;
    const len = (val / total) * c;
    arcs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${getEnergyColor(cls)}" stroke-width="${strokeW}" stroke-dasharray="${len} ${c}" stroke-dashoffset="${-acc}" transform="rotate(-90 ${cx} ${cy})"/>`;
    acc += len;
  });

  return `
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#edf2f8" stroke-width="${strokeW}"/>
      ${arcs}
      <circle cx="${cx}" cy="${cy}" r="${r - strokeW * 0.72}" fill="#ffffff"/>
      <text x="${cx}" y="${cy - 3}" text-anchor="middle" font-size="18" fill="#243a53" font-weight="600">${total}</text>
      <text x="${cx}" y="${cy + 13}" text-anchor="middle" font-size="10" fill="#64788f">buildings</text>
    </svg>
  `;
}

function updateStatsPanel() {
  var donutEl = document.getElementById("legend-donut");
  var donutLabelEl = document.getElementById("legend-donut-label");
  if (!donutEl || !donutLabelEl) return;
  var chartPanelEl = document.getElementById("legend-chart-panel");
  if (chartPanelEl && !chartPanelEl.classList.contains("open")) return;

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

  donutEl.innerHTML = donutChartSVG(counts, total);
  donutLabelEl.textContent = total ? `${total} building${total === 1 ? "" : "s"} in your current view` : "No buildings in this view";
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
    const dotLabelY = y(v) - 12;
    pointMarkup += `
      <g class="dot-group" style="pointer-events:all;cursor:default;">
        <circle cx="${x(i)}" cy="${y(v)}" r="8" fill="transparent"/>
        <circle class="chart-dot" cx="${x(i)}" cy="${y(v)}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="1.2">
          <title>${months[i]} - ${v.toFixed(2)} MWh</title>
        </circle>
        <g class="chart-tip">
          <rect x="${x(i) - 35}" y="${dotLabelY - 18}" width="70" height="16" rx="5" ry="5" fill="rgba(17,24,39,0.92)"/>
          <text x="${x(i)}" y="${dotLabelY - 6}" font-size="9.8" fill="#ffffff" text-anchor="middle">${v.toFixed(2)} MWh</text>
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
  const apiUrl = p.api_url || p.open_api_url || p.api || "";
  const safeApiUrl = String(apiUrl).replace(/'/g, "%27");
  const heatIndicator = parseHeatingIndicator(p.heating_indicator);
  const indicatorClass = heatIndicator === null ? "neutral" : (heatIndicator > 0 ? "over" : (heatIndicator < 0 ? "under" : "neutral"));
  const indicatorWidth = heatIndicator === null ? 0 : Math.min(50, Math.abs(heatIndicator) * 0.5);
  const indicatorPointPos = heatIndicator === null ? 50 : Math.max(0, Math.min(100, 50 + (heatIndicator * 0.5)));
  const indicatorEdgeClass = indicatorPointPos >= 92 ? "edge-right" : (indicatorPointPos <= 8 ? "edge-left" : "");
  const indicatorValueText = fmtPct(heatIndicator);

  const detailRows = [
    ["Ground floors", bd(p, "BuildingBasicData.BuildingGroundFloors")],
    ["Underground floors", bd(p, "BuildingBasicData.BuildingUndergroundFloors")],
    ["Apartments", bd(p, "BuildingBasicData.BuildingPregCount")],
    ["Total area", (() => { const val = bd(p, "BuildingOrPremiseGroupExplicationData.TotalArea"); return val && val !== "-" ? `${val} m²` : val; })()],
    ["Useful area", (() => { const val = bd(p, "BuildingOrPremiseGroupExplicationData.TotalAreaDetails.ExpedientArea"); return val && val !== "-" ? `${val} m²` : val; })()],
    //["Heated area", p.reference_area_m2 ? `${p.reference_area_m2} m²` : "-"],
    ["Construction year", p.manufacture_year || "-"],
    ["Construction materials", p.heavy_light || "-"]
  ].map(([label, value]) => `
    <div class="fact-row">
      <div class="fact-label">${label}</div>
      <div class="fact-value">${value ?? "-"}</div>
    </div>
  `).join("");

  return `
    <div class="building-popup">
      <div class="building-popup-header">
        <div>
          <div class="title-line">
          <h3 class="building-title">Building profile</h3>
          <span class="energy-badge" style="background:${energyColor};">Class ${cls}</span>
          </div>
          <div class="building-subtitle">Cadastral number: ${p.CODE || "-"}</div>
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
        </div>
      </div>

      <div class="popup-actions">
        <button class="api-btn" ${apiUrl ? `onclick="window.open('${safeApiUrl}','_blank')"` : "disabled"}>Open API ↗</button>
      </div>
    </div>
  `;
}

function onEachFeature(feature, layer) {
  layer.on({ mouseover: highlightFeature, mouseout: resetHighlight });
  layer.bindPopup(function () {
    return buildPopupContent(feature);
  }, { maxWidth: 740 });
}

/* ═══════════════════════════════════════════════════
   RENDER BUILDINGS
═══════════════════════════════════════════════════ */
function shouldRenderFeature(feature) {
  const p = feature && feature.properties;
  if (!p) return false;
  const energyClass = getFeatureEnergyClass(feature);
  if (!energyClass) return false;
  return activeClasses.has(energyClass);
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
      if (b.isValid()) map.fitBounds(b);
    }
  }

  addChunk();
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
    <div class="legend-chart-panel" id="legend-chart-panel">
      <div class="legend-chart-title">Visible buildings by class</div>
      <div id="legend-donut"></div>
      <div id="legend-donut-label" class="legend-donut-label">0 visible buildings</div>
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
      if (action === "all")  activeClasses = new Set(CLASS_ORDER);
      if (action === "none") activeClasses = new Set();
      if (action === "help") {
        helpPanel.classList.toggle("open");
        return;
      }
      if (action === "chart") {
        chartPanel.classList.toggle("open");
        updateStatsPanel();
        return;
      }
      updateLegendUI();
      renderBuildings();
      return;
    }
    const row = e.target.closest("[data-cls]");
    if (!row) return;
    const cls = row.getAttribute("data-cls");
    if (activeClasses.has(cls)) activeClasses.delete(cls);
    else activeClasses.add(cls);
    updateLegendUI();
    renderBuildings();
  });

  return div;
};

legend.addTo(map);

map.on("moveend zoomend", updateStatsPanel);

/* ═══════════════════════════════════════════════════
   LOAD GEOJSON
═══════════════════════════════════════════════════ */
fetch((window.BUILDINGS_DATA_URL || "all_buildings_with_building_fields_heat_only_all_steps.json") + "?v=" + Date.now())
  .then(r => r.text())
  .then(text => {
    // Replace NaN with null (invalid JSON fix)
    const cleanedText = text.replace(/:\s*NaN\b/g, ': null');
    return JSON.parse(cleanedText);
  })
  .then(data => {
    console.log("[map] Loaded GeoJSON features:", Array.isArray(data.features) ? data.features.length : 0);
    allData = data;
    renderBuildings(true);
  })
  .catch(err => console.error(err));

/* Initial sync after map is ready */
map.whenReady(function () {
  setTimeout(syncMiniMap, 100);
});