(function () {
    'use strict';

    // ── DOM references ────────────────────────────────────────────────────────
    var generationCards   = document.querySelectorAll('#generation-type-group .dt-tab-card');
    var latInput           = document.getElementById('lat-input');
    var lonInput            = document.getElementById('lon-input');

    var runBtn              = document.getElementById('run-forecast-btn');
    var loadingPanel        = document.getElementById('loading-panel');
    var resultsSection      = document.getElementById('results-section');
    var compareToggle       = document.getElementById('compare-toggle');
    var compareToggleHint   = document.getElementById('compare-toggle-hint');
    var compareToggleCta    = document.getElementById('compare-toggle-cta');
    var singleModeEls       = document.querySelectorAll('.single-mode-only');
    var compareModeEls      = document.querySelectorAll('.compare-mode-only');
    var runPanelTitle       = document.getElementById('run-panel-title');
    var runPanelSubtitle    = document.getElementById('run-panel-subtitle');
    var cmResultsSection    = document.getElementById('cm-results-section');

    var exportJsonBtn       = document.getElementById('export-json-btn');
    var saveOpenJupyterBtn  = document.getElementById('save-open-jupyterhub-btn');

    var CEDER_SITE = { lat: 41.68, lon: -2.53 };

    // ── State ─────────────────────────────────────────────────────────────────
    var selectedGeneration   = 'wind';
    var lastApiResponse      = null;
    var lastGenerationType   = null;
    var powerChartRoot       = null;
    var chartResetZoomFn     = null;
    var activeController     = null;

    // Field names confirmed against live /api/v1/forecast/wind and /forecast/solar responses.
    // stat: 'avg' for wind (standard resource-assessment metric) vs 'max' for solar (peak irradiance,
    // more meaningful than a 24h average dragged down by night-time zeros).
    var WEATHER_META = {
        wind:  { rawField: 'wind_speed',  correctedField: 'wind_speed_corrected',  label: 'Avg Wind Speed', unit: 'm/s',  rawLegend: 'Wind Speed',  correctedLegend: 'Wind Speed (corrected)',  decimals: 1, stat: 'avg' },
        solar: { rawField: 'irradiance',  correctedField: 'irradiance_corrected',  label: 'Max Irradiance', unit: 'W/m²', rawLegend: 'Irradiance', correctedLegend: 'Irradiance (corrected)', decimals: 0, stat: 'max' },
    };

    // ── Generation type cards ─────────────────────────────────────────────────
    generationCards.forEach(function (card) {
        card.addEventListener('click', function () {
            generationCards.forEach(function (c) {
                c.classList.remove('active');
                c.setAttribute('aria-pressed', 'false');
            });
            card.classList.add('active');
            card.setAttribute('aria-pressed', 'true');
            selectedGeneration = card.dataset.generation;
        });
        card.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
        });
    });

    // ── Location map ──────────────────────────────────────────────────────────
    var toggleMapBtn      = document.getElementById('toggle-map-btn');
    var locationMapWrapper = document.getElementById('location-map-wrapper');
    var locationMap        = null;
    var locationMarker     = null;

    function setMapMarker(lat, lon, recenter) {
        if (!locationMap) return;
        locationMarker.setLatLng([lat, lon]);
        if (recenter) locationMap.setView([lat, lon], locationMap.getZoom());
    }

    function initLocationMap() {
        if (locationMap) return;
        var lat = parseFloat(latInput.value) || CEDER_SITE.lat;
        var lon = parseFloat(lonInput.value) || CEDER_SITE.lon;

        locationMap = L.map('location-map').setView([lat, lon], 7);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 18,
        }).addTo(locationMap);

        locationMarker = L.marker([lat, lon], { draggable: true }).addTo(locationMap);

        locationMap.on('click', function (e) {
            latInput.value = e.latlng.lat.toFixed(4);
            lonInput.value = e.latlng.lng.toFixed(4);
            setMapMarker(e.latlng.lat, e.latlng.lng, false);
        });

        locationMarker.on('dragend', function () {
            var pos = locationMarker.getLatLng();
            latInput.value = pos.lat.toFixed(4);
            lonInput.value = pos.lng.toFixed(4);
        });
    }

    toggleMapBtn.addEventListener('click', function () {
        var willShow = locationMapWrapper.classList.contains('d-none');
        locationMapWrapper.classList.toggle('d-none');
        if (willShow) {
            initLocationMap();
            // Leaflet needs a visible container to size itself correctly.
            setTimeout(function () { locationMap.invalidateSize(); }, 0);
        }
    });

    // ── Compare-with-a-second-model toggle ──────────────────────────────────────
    compareToggle.addEventListener('change', function () {
        var on = compareToggle.checked;
        singleModeEls.forEach(function (el) { el.classList.toggle('d-none', on); });
        compareModeEls.forEach(function (el) { el.classList.toggle('d-none', !on); });
        compareToggleHint.textContent = on
            ? 'ON'
            : 'OFF — Forecasting one configuration';
        compareToggleCta.classList.toggle('d-none', on);
        runBtn.innerHTML = on ? '<span class="fas fa-chart-line me-1"></span>Compare' : 'Run forecast &rarr;';
        runPanelTitle.textContent = on ? '5-day forecast · 15-minute resolution' : '5-day forecast · 15-minute resolution';
        runPanelSubtitle.textContent = on
            ? 'Both models run over the same horizon and weather source, so totals are directly comparable.'
            : 'The forecast horizon and resolution are fixed by the EnergyPrediction service.';
        resultsSection.classList.add('d-none');
        cmResultsSection.classList.add('d-none');
    });

    // ── CSRF helper ───────────────────────────────────────────────────────────
    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // ── Run Forecast ──────────────────────────────────────────────────────────
    runBtn.addEventListener('click', function () {
        if (compareToggle.checked) {
            runCompareForecast();
        } else {
            runSingleForecast();
        }
    });

    function runSingleForecast() {
        var lat = parseFloat(latInput.value);
        var lon = parseFloat(lonInput.value);
        if (isNaN(lat) || lat < -90 || lat > 90 || isNaN(lon) || lon < -180 || lon > 180) {
            alert('Please provide valid latitude (-90 to 90) and longitude (-180 to 180) values.');
            return;
        }

        runBtn.disabled = true;
        runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Running…';
        loadingPanel.classList.remove('d-none');
        resultsSection.classList.add('d-none');

        var existingErrorAlert = document.getElementById('forecast-error-alert');
        if (existingErrorAlert) existingErrorAlert.remove();

        var payload = { generation_type: selectedGeneration, lat: lat, lon: lon };
        var snapshot = { generationType: selectedGeneration, lat: lat, lon: lon };

        if (activeController) activeController.abort();
        activeController = new AbortController();
        var signal = activeController.signal;

        fetch(window.CIEMAT_CONFIG.forecastUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(payload),
            signal: signal,
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Forecast failed.';
                    try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
                    throw new Error(msg);
                });
            }
            return resp.json();
        })
        .then(function (data) {
            activeController = null;
            lastApiResponse    = data;
            lastGenerationType = snapshot.generationType;
            loadingPanel.classList.add('d-none');
            populateResults(data, snapshot);
            cmResultsSection.classList.add('d-none');
            resultsSection.classList.remove('d-none');
            runBtn.disabled = false;
            runBtn.innerHTML = 'Run forecast &rarr;';
            resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        })
        .catch(function (err) {
            if (err.name === 'AbortError') return;
            activeController = null;
            loadingPanel.classList.add('d-none');
            runBtn.disabled = false;
            runBtn.innerHTML = 'Run forecast &rarr;';
            var alertEl = document.createElement('div');
            alertEl.id = 'forecast-error-alert';
            alertEl.className = 'alert alert-subtle-danger rounded-3 mb-4 d-flex align-items-center gap-2';
            alertEl.setAttribute('role', 'alert');
            var iconEl = document.createElement('span');
            iconEl.className = 'fas fa-circle-xmark flex-shrink-0';
            var msgEl = document.createElement('span');
            msgEl.textContent = err.message || 'An unexpected error occurred. Please try again.';
            alertEl.appendChild(iconEl);
            alertEl.appendChild(msgEl);
            loadingPanel.insertAdjacentElement('afterend', alertEl);
            setTimeout(function () { if (alertEl.parentNode) alertEl.remove(); }, 8000);
        });
    }

    // ── Data helpers ──────────────────────────────────────────────────────────
    function extractPoints(data) {
        var points = (data && data.points) || [];
        return points
            .map(function (p) {
                var t = new Date(p.timestamp);
                return {
                    time:      t,
                    timestamp: p.timestamp,
                    power:     +p.power_kw || 0,
                    weather:   p,
                };
            })
            .filter(function (p) { return !isNaN(p.time.getTime()); })
            .sort(function (a, b) { return a.time - b.time; });
    }

    function computeTotalEnergyKwh(points) {
        if (points.length < 2) return points.length === 1 ? points[0].power * 0.25 : 0;
        var total = 0;
        for (var i = 1; i < points.length; i++) {
            var dtHours = (points[i].time - points[i - 1].time) / 3600000;
            if (dtHours > 0 && dtHours < 6) {
                total += (points[i].power + points[i - 1].power) / 2 * dtHours;
            }
        }
        return total;
    }

    function average(values) {
        var valid = values.filter(function (v) { return typeof v === 'number' && !isNaN(v); });
        if (!valid.length) return null;
        return valid.reduce(function (a, b) { return a + b; }, 0) / valid.length;
    }

    function hasCorrected(points, meta) {
        return points.some(function (p) { return p.weather[meta.correctedField] != null; });
    }

    // Generating hours: total time span where power is above a near-zero threshold.
    function computeGeneratingHours(points) {
        if (points.length < 2) return (points.length === 1 && points[0].power > 0.01) ? 0.25 : 0;
        var hours = 0;
        for (var i = 1; i < points.length; i++) {
            var dtHours = (points[i].time - points[i - 1].time) / 3600000;
            if (dtHours > 0 && dtHours < 6 && (points[i].power > 0.01 || points[i - 1].power > 0.01)) {
                hours += dtHours;
            }
        }
        return hours;
    }

    // ── Populate results from API data ────────────────────────────────────────
    function populateResults(data, snapshot) {
        var meta   = WEATHER_META[snapshot.generationType];
        var points = extractPoints(data);

        var now = new Date();
        var ts  = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                + ' ' + now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

        document.getElementById('res-generation-type').textContent = snapshot.generationType === 'wind' ? 'Wind Power' : 'Solar PV';
        document.getElementById('res-timestamp').textContent       = ts;
        document.getElementById('res-location').textContent        = snapshot.lat.toFixed(4) + ', ' + snapshot.lon.toFixed(4);

        var powers = points.map(function (p) { return p.power; });
        var peak = powers.length ? Math.max.apply(null, powers) : null;
        var peakPoint = points.filter(function (p) { return p.power === peak; })[0];
        var totalEnergy = computeTotalEnergyKwh(points);
        var generatingHours = computeGeneratingHours(points);

        var weatherField = hasCorrected(points, meta) ? meta.correctedField : meta.rawField;
        var weatherValues = points.map(function (p) { return +p.weather[weatherField]; })
            .filter(function (v) { return !isNaN(v); });
        var weatherStat = meta.stat === 'max'
            ? (weatherValues.length ? Math.max.apply(null, weatherValues) : null)
            : average(weatherValues);

        document.getElementById('res-peak').textContent  = peak != null ? peak.toFixed(2) : '—';
        document.getElementById('res-total').textContent = points.length ? totalEnergy.toLocaleString(undefined, { maximumFractionDigits: 1 }) : '—';
        document.getElementById('res-gen-hours').textContent = points.length ? generatingHours.toLocaleString(undefined, { maximumFractionDigits: 1 }) : '—';

        document.getElementById('res-weather-label').textContent = meta.label;
        document.getElementById('res-weather-unit').textContent  = meta.unit;
        document.getElementById('res-weather').textContent       = weatherStat != null ? weatherStat.toFixed(meta.decimals) : '—';

        // Insights
        document.getElementById('insight-peak').textContent = peak != null ? peak.toFixed(2) + ' kW' : '—';
        document.getElementById('insight-peak-time').textContent = peakPoint
            ? peakPoint.time.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ' ' + peakPoint.time.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
            : '—';

        // Config summary
        document.getElementById('sum-generation-type').textContent = snapshot.generationType === 'wind' ? 'Wind Power (NED100)' : 'Solar PV (Afrisol)';
        document.getElementById('sum-lat').textContent = snapshot.lat.toFixed(4) + '°';
        document.getElementById('sum-lon').textContent = snapshot.lon.toFixed(4) + '°';

        renderChart(points, meta, true);
    }

    // ── Legend row ─────────────────────────────────────────────────────────────
    function setLegend(entries) {
        var row = document.getElementById('chart-legend-row');
        row.innerHTML = '';
        entries.forEach(function (entry) {
            var item = document.createElement('span');
            item.className = 'd-flex align-items-center gap-1 fs-9 text-body-secondary';
            var swatch = document.createElement('span');
            swatch.style.cssText = 'width:12px;height:12px;border-radius:2px;display:inline-block;flex-shrink:0;background:' + entry.color;
            if (entry.dashed) swatch.style.cssText += ';background-image:repeating-linear-gradient(90deg,' + entry.color + ' 0 3px,transparent 3px 6px);background-color:transparent';
            var label = document.createElement('span');
            label.textContent = entry.label;
            item.appendChild(swatch);
            item.appendChild(label);
            row.appendChild(item);
        });
    }

    // ── Chart rendering ───────────────────────────────────────────────────────
    function renderChart(points, meta, forceRebuild) {
        var placeholder = document.getElementById('chart-placeholder-inner');
        var wrapper     = document.getElementById('chart-canvas-wrapper');

        if (powerChartRoot) {
            powerChartRoot.dispose();
            powerChartRoot = null;
        }

        placeholder.style.display = 'none';
        wrapper.style.display     = 'block';

        var root = am5.Root.new('power-chart');
        root.setThemes([am5themes_Animated.new(root)]);
        powerChartRoot = root;

        var styles         = getComputedStyle(document.documentElement);
        var textColor      = am5.color(0x31374a);
        var primaryColor   = am5.color(styles.getPropertyValue('--phoenix-primary').trim());
        var turquoiseColor = am5.color(styles.getPropertyValue('--phoenix-turquoise').trim());
        var warningColor   = am5.color(styles.getPropertyValue('--phoenix-warning').trim());

        var chart = root.container.children.push(am5xy.XYChart.new(root, {
            layout: root.verticalLayout,
            panX: true,
            panY: false,
            wheelX: 'panX',
            wheelY: 'none',
            pinchZoomX: true,
        }));
        chart.zoomOutButton.set('forceHidden', true);

        var xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 60 });
        xRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var xAxis = chart.xAxes.push(am5xy.DateAxis.new(root, {
            baseInterval: { timeUnit: 'minute', count: 15 },
            renderer: xRenderer,
            tooltip: am5.Tooltip.new(root, {}),
        }));

        var yRenderer = am5xy.AxisRendererY.new(root, {});
        yRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, {
            renderer: yRenderer,
            extraMax: 0.1,
            min: 0,
        }));
        yAxis.children.unshift(am5.Label.new(root, {
            text: 'Power (kW)', rotation: -90, y: am5.p50, centerX: am5.p50, fill: primaryColor, fontSize: 11,
        }));

        var yRendererWeather = am5xy.AxisRendererY.new(root, { opposite: true });
        yRendererWeather.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var yAxisWeather = chart.yAxes.push(am5xy.ValueAxis.new(root, {
            renderer: yRendererWeather,
            extraMax: 0.1,
            min: 0,
        }));
        yAxisWeather.children.push(am5.Label.new(root, {
            text: meta.unit, rotation: -90, y: am5.p50, centerX: am5.p50, fill: turquoiseColor, fontSize: 11,
        }));

        var yRendererTemp = am5xy.AxisRendererY.new(root, { opposite: true });
        yRendererTemp.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var yAxisTemp = chart.yAxes.push(am5xy.ValueAxis.new(root, {
            renderer: yRendererTemp,
            extraMax: 0.2,
        }));
        yAxisTemp.set('marginRight', 40);
        yAxisTemp.children.push(am5.Label.new(root, {
            text: '°C', rotation: -90, y: am5.p50, centerX: am5.p50, fill: warningColor, fontSize: 11,
        }));

        var powerData = points.map(function (p) { return { date: p.time.getTime(), value: p.power }; });

        var powerSeries = chart.series.push(am5xy.LineSeries.new(root, {
            name: 'Power (kW)',
            xAxis: xAxis,
            yAxis: yAxis,
            valueYField: 'value',
            valueXField: 'date',
            stroke: primaryColor,
            fill: primaryColor,
            tooltip: am5.Tooltip.new(root, { labelText: 'Power: {valueY.formatNumber("#,###.##")} kW' }),
        }));
        powerSeries.strokes.template.setAll({ strokeWidth: 2 });
        powerSeries.fills.template.setAll({ fillOpacity: 0.12, visible: true });
        powerSeries.data.setAll(powerData);
        powerSeries.appear();

        var legendEntries = [{ color: 'var(--phoenix-primary)', label: 'Power (kW)' }];
        var scrollbarSeries = powerSeries;

        function addWeatherSeries(field, name, dashed) {
            var seriesData = points.map(function (p) { return { date: p.time.getTime(), value: +p.weather[field] }; });
            var series = chart.series.push(am5xy.LineSeries.new(root, {
                name: name,
                xAxis: xAxis,
                yAxis: yAxisWeather,
                valueYField: 'value',
                valueXField: 'date',
                stroke: turquoiseColor,
                tooltip: am5.Tooltip.new(root, { labelText: name + ': {valueY.formatNumber("#,###.##")} ' + meta.unit }),
            }));
            series.strokes.template.setAll(dashed
                ? { strokeWidth: 1.25, strokeDasharray: [3, 3], strokeOpacity: 0.8 }
                : { strokeWidth: 1.75 });
            series.data.setAll(seriesData);
            series.appear();
            legendEntries.push({ color: 'var(--phoenix-turquoise)', label: name, dashed: dashed });
        }

        if (hasCorrected(points, meta)) {
            addWeatherSeries(meta.rawField, meta.rawLegend, true);
            addWeatherSeries(meta.correctedField, meta.correctedLegend, false);
        } else {
            addWeatherSeries(meta.rawField, meta.rawLegend, false);
        }

        var tempData = points.map(function (p) { return { date: p.time.getTime(), value: +p.weather.temperature }; });
        var tempSeries = chart.series.push(am5xy.LineSeries.new(root, {
            name: 'Temperature',
            xAxis: xAxis,
            yAxis: yAxisTemp,
            valueYField: 'value',
            valueXField: 'date',
            stroke: warningColor,
            tooltip: am5.Tooltip.new(root, { labelText: 'Temperature: {valueY.formatNumber("#,###.#")} °C' }),
        }));
        tempSeries.strokes.template.setAll({ strokeWidth: 1.25, strokeDasharray: [6, 3] });
        tempSeries.data.setAll(tempData);
        tempSeries.appear();
        legendEntries.push({ color: 'var(--phoenix-warning)', label: 'Temperature (°C)', dashed: true });

        setLegend(legendEntries);

        // ── Range scrollbar (zoom/pan) ──────────────────────────────────────
        var scrollbarX = chart.set('scrollbarX', am5xy.XYChartScrollbar.new(root, {
            orientation: 'horizontal',
            height: 50,
        }));
        chart.bottomAxesContainer.children.push(scrollbarX);
        var sbXAxis = scrollbarX.chart.xAxes.push(am5xy.DateAxis.new(root, {
            baseInterval: { timeUnit: 'minute', count: 15 },
            renderer: am5xy.AxisRendererX.new(root, {}),
        }));
        var sbYAxis = scrollbarX.chart.yAxes.push(am5xy.ValueAxis.new(root, {
            renderer: am5xy.AxisRendererY.new(root, {}),
        }));
        var sbSeries = scrollbarX.chart.series.push(am5xy.LineSeries.new(root, {
            xAxis: sbXAxis,
            yAxis: sbYAxis,
            valueYField: 'value',
            valueXField: 'date',
        }));
        sbSeries.data.setAll(powerData);

        chart.set('cursor', am5xy.XYCursor.new(root, { behavior: 'zoomX' }));
        chart.appear(1000, 100);

        chartResetZoomFn = function () {
            xAxis.zoom(0, 1);
        };
    }

    document.getElementById('chart-reset-zoom-btn').addEventListener('click', function () {
        if (chartResetZoomFn) chartResetZoomFn();
    });

    // ── Export ────────────────────────────────────────────────────────────────
    function triggerDownload(content, filename, mimeType) {
        var blob = new Blob([content], { type: mimeType });
        var url  = URL.createObjectURL(blob);
        var a    = document.createElement('a');
        a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
    }

    exportJsonBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        triggerDownload(JSON.stringify(lastApiResponse, null, 2),
            'ciemat-forecast-' + (lastGenerationType || 'result') + '.json', 'application/json');
        exportJsonBtn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { exportJsonBtn.innerHTML = '<span class="fas fa-download me-2"></span>Download JSON'; }, 2000);
    });

    saveOpenJupyterBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;

        var originalHtml = saveOpenJupyterBtn.innerHTML;
        saveOpenJupyterBtn.disabled = true;
        saveOpenJupyterBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…';

        fetch(window.CIEMAT_CONFIG.saveResultUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ twin_slug: 'ciemat-microgrid', data: lastApiResponse }),
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Could not save the result.';
                    try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
                    throw new Error(msg);
                });
            }
            return resp.json();
        })
        .then(function (data) {
            window.open(data.redirect_url, '_blank');
        })
        .catch(function (err) {
            alert(err.message || 'Could not save the result.');
        })
        .finally(function () {
            saveOpenJupyterBtn.disabled = false;
            saveOpenJupyterBtn.innerHTML = originalHtml;
        });
    });

    // ══════════════════════════════════════════════════════════════════════
    // MODE 2: REAL-TIME CALCULATION
    // ══════════════════════════════════════════════════════════════════════

    var calcGenerationCards  = document.querySelectorAll('#calc-generation-type-group .dt-tab-card');
    var calcResolutionCards  = document.querySelectorAll('#calc-resolution-group .dt-tab-card');
    var calcResolutionCard   = document.getElementById('calc-resolution-card');
    var calcResolutionLocked = document.getElementById('calc-resolution-locked-notice');
    var calcWindFields       = document.getElementById('calc-wind-fields');
    var calcSolarFields      = document.getElementById('calc-solar-fields');
    var calcLagFields        = document.getElementById('calc-lag-fields');
    var calcDeviceId         = document.getElementById('calc-device-id');
    var calcRunBtn           = document.getElementById('calc-run-btn');
    var calcLoadingPanel     = document.getElementById('calc-loading-panel');
    var calcResultsSection   = document.getElementById('calc-results-section');
    var calcExportJsonBtn    = document.getElementById('calc-export-json-btn');

    var calcSelectedGeneration = 'wind';
    var calcSelectedResolution = '1s';
    var calcLastResponse       = null;
    var calcActiveController   = null;

    var RESOLUTION_LABELS = { '1s': '1-Second (multilag)', '1min': '1-Minute', '5min': '5-Minute', 'solar': 'Real-time' };
    var CALC_DEVICE_DEFAULTS = { wind: 'NED100-01', solar: 'Afrisol-01' };

    function highlightResolutionCards(res) {
        calcResolutionCards.forEach(function (c) { c.classList.toggle('active', c.dataset.resolution === res); });
    }

    function setCalcResolution(res) {
        calcSelectedResolution = res;
        highlightResolutionCards(res);
        calcLagFields.classList.toggle('d-none', res !== '1s');
    }

    function setCalcGeneration(gen) {
        calcSelectedGeneration = gen;
        calcGenerationCards.forEach(function (c) { c.classList.toggle('active', c.dataset.generation === gen); });
        // Only auto-fill the device id if it still holds one of the known defaults (or is empty) -
        // a value the user typed themselves must survive switching generation type back and forth.
        var deviceIdIsDefault = !calcDeviceId.value
            || calcDeviceId.value === CALC_DEVICE_DEFAULTS.wind
            || calcDeviceId.value === CALC_DEVICE_DEFAULTS.solar;
        if (gen === 'solar') {
            calcWindFields.classList.add('d-none');
            calcSolarFields.classList.remove('d-none');
            calcResolutionCard.classList.add('profiles-locked');
            calcResolutionLocked.classList.remove('d-none');
            if (deviceIdIsDefault) calcDeviceId.value = CALC_DEVICE_DEFAULTS.solar;
            // No resolution applies to solar - dim every card, none should look selected.
            highlightResolutionCards(null);
        } else {
            calcWindFields.classList.remove('d-none');
            calcSolarFields.classList.add('d-none');
            calcResolutionCard.classList.remove('profiles-locked');
            calcResolutionLocked.classList.add('d-none');
            if (deviceIdIsDefault) calcDeviceId.value = CALC_DEVICE_DEFAULTS.wind;
            // Restore whichever wind resolution was selected before switching to solar.
            highlightResolutionCards(calcSelectedResolution);
        }
    }

    calcGenerationCards.forEach(function (card) {
        card.addEventListener('click', function () { setCalcGeneration(card.dataset.generation); });
    });
    calcResolutionCards.forEach(function (card) {
        card.addEventListener('click', function () {
            if (calcSelectedGeneration === 'solar') return;
            setCalcResolution(card.dataset.resolution);
        });
    });

    function collectCalcPayload() {
        if (calcSelectedGeneration === 'solar') {
            return {
                resolution: 'solar',
                device_id: calcDeviceId.value,
                radiation: parseFloat(document.getElementById('calc-radiation').value),
                t_ambiente: parseFloat(document.getElementById('calc-t-ambiente').value),
            };
        }
        var payload = {
            resolution: calcSelectedResolution,
            device_id: calcDeviceId.value,
            wind_speed: parseFloat(document.getElementById('calc-wind-speed').value),
            rpm: parseFloat(document.getElementById('calc-rpm').value),
            temperature: parseFloat(document.getElementById('calc-temperature').value),
            pitch: parseFloat(document.getElementById('calc-pitch').value),
        };
        if (calcSelectedResolution === '1s') {
            payload.wind_speed_lag_5s  = parseFloat(document.getElementById('calc-ws-lag5').value);
            payload.wind_speed_lag_10s = parseFloat(document.getElementById('calc-ws-lag10').value);
            payload.wind_speed_lag_20s = parseFloat(document.getElementById('calc-ws-lag20').value);
            payload.pitch_lag_5s       = parseFloat(document.getElementById('calc-pitch-lag5').value);
        }
        return payload;
    }

    function showRunError(afterEl, message) {
        var existing = document.getElementById('run-error-alert');
        if (existing) existing.remove();
        var alertEl = document.createElement('div');
        alertEl.id = 'run-error-alert';
        alertEl.className = 'alert alert-subtle-danger rounded-3 mb-4 d-flex align-items-center gap-2';
        alertEl.setAttribute('role', 'alert');
        alertEl.innerHTML = '<span class="fas fa-circle-xmark flex-shrink-0"></span><span></span>';
        alertEl.querySelector('span:last-child').textContent = message;
        afterEl.insertAdjacentElement('afterend', alertEl);
        setTimeout(function () { if (alertEl.parentNode) alertEl.remove(); }, 8000);
    }

    calcRunBtn.addEventListener('click', function () {
        var payload = collectCalcPayload();

        calcRunBtn.disabled = true;
        calcRunBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Calculating…';
        calcLoadingPanel.classList.remove('d-none');
        calcResultsSection.classList.add('d-none');

        if (calcActiveController) calcActiveController.abort();
        calcActiveController = new AbortController();

        fetch(window.CIEMAT_CONFIG.calculateUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(payload),
            signal: calcActiveController.signal,
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Calculation failed.';
                    try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
                    throw new Error(msg);
                });
            }
            return resp.json();
        })
        .then(function (data) {
            calcActiveController = null;
            calcLastResponse = data;
            calcLoadingPanel.classList.add('d-none');

            var powerW  = +data.power_w;
            var powerKw = powerW / 1000;
            document.getElementById('calc-res-model').textContent = calcSelectedGeneration === 'wind' ? 'Wind Power' : 'Solar PV';
            document.getElementById('calc-res-power-kw').textContent = powerKw.toLocaleString(undefined, { maximumFractionDigits: 2 });
            document.getElementById('calc-res-power-w').textContent  = powerW.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' W';
            document.getElementById('calc-res-device').textContent   = payload.device_id;
            document.getElementById('calc-res-generation-type').textContent = calcSelectedGeneration === 'wind' ? 'Wind Power (NED100)' : 'Solar PV (Afrisol)';
            document.getElementById('calc-res-resolution').textContent = RESOLUTION_LABELS[payload.resolution] || '—';
            var now = new Date();
            document.getElementById('calc-res-timestamp').textContent = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                + ' ' + now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

            calcResultsSection.classList.remove('d-none');
            calcRunBtn.disabled = false;
            calcRunBtn.innerHTML = 'Calculate power output &rarr;';
        })
        .catch(function (err) {
            if (err.name === 'AbortError') return;
            calcActiveController = null;
            calcLoadingPanel.classList.add('d-none');
            calcRunBtn.disabled = false;
            calcRunBtn.innerHTML = 'Calculate power output &rarr;';
            showRunError(calcLoadingPanel, err.message || 'An unexpected error occurred. Please try again.');
        });
    });

    calcExportJsonBtn.addEventListener('click', function () {
        if (!calcLastResponse) return;
        triggerDownload(JSON.stringify(calcLastResponse, null, 2), 'ciemat-calculation-result.json', 'application/json');
        calcExportJsonBtn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { calcExportJsonBtn.innerHTML = '<span class="fas fa-download me-2"></span>Download JSON'; }, 2000);
    });

    // ══════════════════════════════════════════════════════════════════════
    // MODE 3: MODEL COMPARATOR
    // ══════════════════════════════════════════════════════════════════════

    var cmpRunBtn         = document.getElementById('cmp-run-btn');
    var cmpLoadingPanel   = document.getElementById('cmp-loading-panel');
    var cmpResultsSection = document.getElementById('cmp-results-section');
    var cmpExportJsonBtn  = document.getElementById('cmp-export-json-btn');

    var cmpLastResponse     = null;
    var cmpActiveController = null;
    var compareChartRoot    = null;

    function collectComparePayload() {
        return {
            device_id: document.getElementById('cmp-device-id').value,
            wind_speed: parseFloat(document.getElementById('cmp-wind-speed').value),
            rpm: parseFloat(document.getElementById('cmp-rpm').value),
            temperature: parseFloat(document.getElementById('cmp-temperature').value),
            pitch: parseFloat(document.getElementById('cmp-pitch').value),
            wind_speed_lag_5s:  parseFloat(document.getElementById('cmp-ws-lag5').value),
            wind_speed_lag_10s: parseFloat(document.getElementById('cmp-ws-lag10').value),
            wind_speed_lag_20s: parseFloat(document.getElementById('cmp-ws-lag20').value),
            pitch_lag_5s:       parseFloat(document.getElementById('cmp-pitch-lag5').value),
        };
    }

    cmpRunBtn.addEventListener('click', function () {
        var payload = collectComparePayload();

        cmpRunBtn.disabled = true;
        cmpRunBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Comparing…';
        cmpLoadingPanel.classList.remove('d-none');
        cmpResultsSection.classList.add('d-none');

        if (cmpActiveController) cmpActiveController.abort();
        cmpActiveController = new AbortController();

        fetch(window.CIEMAT_CONFIG.compareUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(payload),
            signal: cmpActiveController.signal,
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Comparison failed.';
                    try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
                    throw new Error(msg);
                });
            }
            return resp.json();
        })
        .then(function (data) {
            cmpActiveController = null;
            cmpLastResponse = data;
            cmpLoadingPanel.classList.add('d-none');
            populateCompareResults(data.results);
            cmpResultsSection.classList.remove('d-none');
            cmpRunBtn.disabled = false;
            cmpRunBtn.innerHTML = 'Compare models &rarr;';
        })
        .catch(function (err) {
            if (err.name === 'AbortError') return;
            cmpActiveController = null;
            cmpLoadingPanel.classList.add('d-none');
            cmpRunBtn.disabled = false;
            cmpRunBtn.innerHTML = 'Compare models &rarr;';
            showRunError(cmpLoadingPanel, err.message || 'An unexpected error occurred. Please try again.');
        });
    });

    function populateCompareResults(results) {
        var kw1min = results['1min'] / 1000;
        var kw5min = results['5min'] / 1000;
        var kw1s   = results['1s'] / 1000;

        document.getElementById('cmp-res-1min').textContent = kw1min.toFixed(2);
        document.getElementById('cmp-res-5min').textContent = kw5min.toFixed(2);
        document.getElementById('cmp-res-1s').textContent   = kw1s.toFixed(2);

        var baseAvg = (kw1min + kw5min) / 2;
        var diffPct = baseAvg !== 0 ? ((kw1s - baseAvg) / baseAvg) * 100 : 0;
        var diffText = (diffPct >= 0 ? '+' : '') + diffPct.toFixed(1) + '%';
        document.getElementById('cmp-insight-diff').textContent = diffText;

        renderCompareChart({ '1-Minute': kw1min, '5-Minute': kw5min, '1-Second': kw1s });
    }

    function renderCompareChart(values) {
        if (compareChartRoot) { compareChartRoot.dispose(); compareChartRoot = null; }

        var root = am5.Root.new('compare-chart');
        root.setThemes([am5themes_Animated.new(root)]);
        compareChartRoot = root;

        var styles       = getComputedStyle(document.documentElement);
        var textColor    = am5.color(0x31374a);
        var primaryColor = am5.color(styles.getPropertyValue('--phoenix-primary').trim());

        var chart = root.container.children.push(am5xy.XYChart.new(root, {
            panX: false, panY: false, wheelX: 'none', wheelY: 'none',
        }));
        chart.zoomOutButton.set('forceHidden', true);

        var chartData = Object.keys(values).map(function (k) { return { model: k, value: values[k] }; });

        var xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 30 });
        xRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });
        var xAxis = chart.xAxes.push(am5xy.CategoryAxis.new(root, {
            categoryField: 'model', renderer: xRenderer,
        }));
        xAxis.data.setAll(chartData);

        var yRenderer = am5xy.AxisRendererY.new(root, {});
        yRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });
        var yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { renderer: yRenderer, extraMax: 0.1 }));
        yAxis.children.unshift(am5.Label.new(root, {
            text: 'kW', rotation: -90, y: am5.p50, centerX: am5.p50, fill: textColor, fontSize: 11,
        }));

        var series = chart.series.push(am5xy.ColumnSeries.new(root, {
            xAxis: xAxis, yAxis: yAxis, valueYField: 'value', categoryXField: 'model',
            tooltip: am5.Tooltip.new(root, { labelText: '{categoryX}: {valueY.formatNumber("#,###.##")} kW' }),
        }));
        series.columns.template.setAll({ fill: primaryColor, stroke: primaryColor, width: am5.percent(50), cornerRadiusTL: 4, cornerRadiusTR: 4 });
        series.data.setAll(chartData);
        series.appear();

        chart.appear(800, 100);
    }

    cmpExportJsonBtn.addEventListener('click', function () {
        if (!cmpLastResponse) return;
        triggerDownload(JSON.stringify(cmpLastResponse, null, 2), 'ciemat-model-comparison.json', 'application/json');
        cmpExportJsonBtn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { cmpExportJsonBtn.innerHTML = '<span class="fas fa-download me-2"></span>Download JSON'; }, 2000);
    });

    // ══════════════════════════════════════════════════════════════════════
    // COMPARE MODE (two independently configured models, integrated into the
    // 5-Day Forecast tab via the "Compare with a second model" toggle above)
    // ══════════════════════════════════════════════════════════════════════

    var MODEL_LABELS = { wind: 'Wind NED100', solar: 'Solar Photovoltaic (Afrisol)' };

    var modelAGeneration = document.getElementById('model-a-generation');
    var modelBGeneration = document.getElementById('model-b-generation');
    var modelALat = document.getElementById('model-a-lat');
    var modelALon = document.getElementById('model-a-lon');
    var modelBLat = document.getElementById('model-b-lat');
    var modelBLon = document.getElementById('model-b-lon');

    var modelASelectedGeneration = 'wind';
    var modelBSelectedGeneration = 'solar';

    function selectModelGeneration(gen, which) {
        if (which === 'a') { modelASelectedGeneration = gen; modelAGeneration.value = gen; }
        else { modelBSelectedGeneration = gen; modelBGeneration.value = gen; }
    }

    modelAGeneration.addEventListener('change', function () { selectModelGeneration(modelAGeneration.value, 'a'); });
    modelBGeneration.addEventListener('change', function () { selectModelGeneration(modelBGeneration.value, 'b'); });

    // Toggle-to-reveal Leaflet picker, mirroring the single-model Location map above.
    function setupToggleMapPicker(toggleBtnId, wrapperId, mapDivId, latEl, lonEl, onSetLatLng) {
        var toggleBtn = document.getElementById(toggleBtnId);
        var wrapper   = document.getElementById(wrapperId);
        var map       = null;
        var marker    = null;

        function init() {
            if (map) return;
            var lat = parseFloat(latEl.value) || CEDER_SITE.lat;
            var lon = parseFloat(lonEl.value) || CEDER_SITE.lon;

            map = L.map(mapDivId).setView([lat, lon], 7);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; OpenStreetMap contributors',
                maxZoom: 18,
            }).addTo(map);

            marker = L.marker([lat, lon], { draggable: true }).addTo(map);

            map.on('click', function (e) {
                latEl.value = e.latlng.lat.toFixed(4);
                lonEl.value = e.latlng.lng.toFixed(4);
                marker.setLatLng(e.latlng);
                onSetLatLng();
            });

            marker.on('dragend', function () {
                var pos = marker.getLatLng();
                latEl.value = pos.lat.toFixed(4);
                lonEl.value = pos.lng.toFixed(4);
                onSetLatLng();
            });
        }

        toggleBtn.addEventListener('click', function () {
            var willShow = wrapper.classList.contains('d-none');
            wrapper.classList.toggle('d-none');
            if (willShow) {
                init();
                setTimeout(function () { map.invalidateSize(); }, 0);
            }
        });

        return {
            recenter: function () {
                if (!map) return;
                var lat = parseFloat(latEl.value), lon = parseFloat(lonEl.value);
                if (isNaN(lat) || isNaN(lon)) return;
                map.setView([lat, lon], map.getZoom());
                marker.setLatLng([lat, lon]);
            },
        };
    }

    var modelAMapPicker = setupToggleMapPicker('model-a-toggle-map-btn', 'model-a-map-wrapper', 'model-a-map', modelALat, modelALon, function () {});
    var modelBMapPicker = setupToggleMapPicker('model-b-toggle-map-btn', 'model-b-map-wrapper', 'model-b-map', modelBLat, modelBLon, function () {});

    document.getElementById('copy-from-a-btn').addEventListener('click', function () {
        modelBLat.value = modelALat.value;
        modelBLon.value = modelALon.value;
        selectModelGeneration(modelASelectedGeneration, 'b');
        modelBMapPicker.recenter();
    });

    var cmResetZoomBtn = document.getElementById('cm-reset-zoom-btn');
    var cmChartRoot     = null;
    var cmResetZoomFn   = null;

    function fetchForecast(generationType, lat, lon, signal) {
        return fetch(window.CIEMAT_CONFIG.forecastUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ generation_type: generationType, lat: lat, lon: lon }),
            signal: signal,
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Forecast failed.';
                    try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
                    throw new Error(msg);
                });
            }
            return resp.json();
        });
    }

    function runCompareForecast() {
        var latA = parseFloat(modelALat.value), lonA = parseFloat(modelALon.value);
        var latB = parseFloat(modelBLat.value), lonB = parseFloat(modelBLon.value);
        if ([latA, lonA, latB, lonB].some(function (v) { return isNaN(v); })) {
            alert('Please provide valid coordinates for both models.');
            return;
        }

        runBtn.disabled = true;
        runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Comparing…';
        loadingPanel.classList.remove('d-none');
        resultsSection.classList.add('d-none');
        cmResultsSection.classList.add('d-none');

        var existingErrorAlert = document.getElementById('forecast-error-alert');
        if (existingErrorAlert) existingErrorAlert.remove();

        var genA = modelASelectedGeneration, genB = modelBSelectedGeneration;

        if (activeController) activeController.abort();
        activeController = new AbortController();
        var signal = activeController.signal;

        Promise.all([
            fetchForecast(genA, latA, lonA, signal),
            fetchForecast(genB, latB, lonB, signal),
        ])
        .then(function (results) {
            activeController = null;
            loadingPanel.classList.add('d-none');
            populateCompareModelsResults(results[0], results[1], genA, genB);
            cmResultsSection.classList.remove('d-none');
            runBtn.disabled = false;
            runBtn.innerHTML = '<span class="fas fa-chart-line me-1"></span>Compare';
            cmResultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        })
        .catch(function (err) {
            if (err.name === 'AbortError') return;
            activeController = null;
            loadingPanel.classList.add('d-none');
            runBtn.disabled = false;
            runBtn.innerHTML = '<span class="fas fa-chart-line me-1"></span>Compare';
            var alertEl = document.createElement('div');
            alertEl.id = 'forecast-error-alert';
            alertEl.className = 'alert alert-subtle-danger rounded-3 mb-4 d-flex align-items-center gap-2';
            alertEl.setAttribute('role', 'alert');
            alertEl.innerHTML = '<span class="fas fa-circle-xmark flex-shrink-0"></span><span></span>';
            alertEl.querySelector('span:last-child').textContent = err.message || 'An unexpected error occurred. Please try again.';
            loadingPanel.insertAdjacentElement('afterend', alertEl);
            setTimeout(function () { if (alertEl.parentNode) alertEl.remove(); }, 8000);
        });
    }

    function populateCompareModelsResults(dataA, dataB, genA, genB) {
        var pointsA = extractPoints(dataA);
        var pointsB = extractPoints(dataB);

        var labelA = MODEL_LABELS[genA] || genA;
        var labelB = MODEL_LABELS[genB] || genB;
        document.getElementById('cm-th-a').textContent = labelA;
        document.getElementById('cm-th-b').textContent = labelB;

        function summarize(points) {
            var powers = points.map(function (p) { return p.power; });
            var peak = powers.length ? Math.max.apply(null, powers) : null;
            return {
                total: computeTotalEnergyKwh(points),
                peak: peak,
                hours: computeGeneratingHours(points),
            };
        }

        var sumA = summarize(pointsA);
        var sumB = summarize(pointsB);

        document.getElementById('cm-total-a').textContent = sumA.total.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' kWh';
        document.getElementById('cm-total-b').textContent = sumB.total.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' kWh';
        document.getElementById('cm-peak-a').textContent  = (sumA.peak != null ? sumA.peak.toFixed(2) : '—') + ' kW';
        document.getElementById('cm-peak-b').textContent  = (sumB.peak != null ? sumB.peak.toFixed(2) : '—') + ' kW';
        document.getElementById('cm-hours-a').textContent = sumA.hours.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' h';
        document.getElementById('cm-hours-b').textContent = sumB.hours.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' h';

        renderCompareModelsChart(pointsA, pointsB, labelA, labelB);
    }

    function renderCompareModelsChart(pointsA, pointsB, labelA, labelB) {
        if (cmChartRoot) { cmChartRoot.dispose(); cmChartRoot = null; }

        var root = am5.Root.new('cm-chart');
        root.setThemes([am5themes_Animated.new(root)]);
        cmChartRoot = root;

        var styles         = getComputedStyle(document.documentElement);
        var textColor      = am5.color(0x31374a);
        var primaryColor   = am5.color(styles.getPropertyValue('--phoenix-primary').trim());
        var purpleColor    = am5.color(styles.getPropertyValue('--phoenix-purple').trim());

        var chart = root.container.children.push(am5xy.XYChart.new(root, {
            layout: root.verticalLayout,
            panX: true,
            panY: false,
            wheelX: 'panX',
            wheelY: 'none',
            pinchZoomX: true,
        }));
        chart.zoomOutButton.set('forceHidden', true);

        var xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 60 });
        xRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });
        var xAxis = chart.xAxes.push(am5xy.DateAxis.new(root, {
            baseInterval: { timeUnit: 'minute', count: 15 },
            renderer: xRenderer,
            tooltip: am5.Tooltip.new(root, {}),
        }));

        var yRenderer = am5xy.AxisRendererY.new(root, {});
        yRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });
        var yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { renderer: yRenderer, extraMax: 0.1, min: 0 }));
        yAxis.children.unshift(am5.Label.new(root, {
            text: 'Power (kW)', rotation: -90, y: am5.p50, centerX: am5.p50, fill: textColor, fontSize: 11,
        }));

        function addSeries(points, name, color) {
            var data = points.map(function (p) { return { date: p.time.getTime(), value: p.power }; });
            var series = chart.series.push(am5xy.LineSeries.new(root, {
                name: name,
                xAxis: xAxis,
                yAxis: yAxis,
                valueYField: 'value',
                valueXField: 'date',
                stroke: color,
                fill: color,
                tooltip: am5.Tooltip.new(root, { labelText: name + ': {valueY.formatNumber("#,###.##")} kW' }),
            }));
            series.strokes.template.setAll({ strokeWidth: 2 });
            series.fills.template.setAll({ fillOpacity: 0.1, visible: true });
            series.data.setAll(data);
            series.appear();
            return data;
        }

        var dataAForScrollbar = addSeries(pointsA, labelA, primaryColor);
        var dataBForScrollbar = addSeries(pointsB, labelB, purpleColor);

        var scrollbarX = chart.set('scrollbarX', am5xy.XYChartScrollbar.new(root, {
            orientation: 'horizontal',
            height: 50,
        }));
        chart.bottomAxesContainer.children.push(scrollbarX);
        var sbXAxis = scrollbarX.chart.xAxes.push(am5xy.DateAxis.new(root, {
            baseInterval: { timeUnit: 'minute', count: 15 },
            renderer: am5xy.AxisRendererX.new(root, {}),
        }));
        var sbYAxis = scrollbarX.chart.yAxes.push(am5xy.ValueAxis.new(root, {
            renderer: am5xy.AxisRendererY.new(root, {}),
        }));
        var sbSeriesA = scrollbarX.chart.series.push(am5xy.LineSeries.new(root, {
            xAxis: sbXAxis, yAxis: sbYAxis, valueYField: 'value', valueXField: 'date',
        }));
        sbSeriesA.data.setAll(dataAForScrollbar);
        var sbSeriesB = scrollbarX.chart.series.push(am5xy.LineSeries.new(root, {
            xAxis: sbXAxis, yAxis: sbYAxis, valueYField: 'value', valueXField: 'date',
        }));
        sbSeriesB.data.setAll(dataBForScrollbar);

        chart.set('cursor', am5xy.XYCursor.new(root, { behavior: 'zoomX' }));
        chart.appear(1000, 100);

        cmResetZoomFn = function () { xAxis.zoom(0, 1); };
    }

    cmResetZoomBtn.addEventListener('click', function () {
        if (cmResetZoomFn) cmResetZoomFn();
    });

}());
