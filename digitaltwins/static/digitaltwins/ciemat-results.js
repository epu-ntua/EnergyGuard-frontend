/* Drawing CIEMAT results - the 5-day forecast, the comparison of two forecasts,
the real-time calculation and the model comparator - with their download and
JupyterHub buttons. Shared by the workspace, which calls these after a run, and
the page of a stored run (ciemat-run.js). Each function expects the markup of its
partial in digitaltwins/ciemat/; buttons of partials not on the page are skipped. */
(function () {
    'use strict';

    // Field names confirmed against live /api/v1/forecast/wind and /forecast/solar responses.
    // stat: 'avg' for wind (standard resource-assessment metric) vs 'max' for solar (peak irradiance,
    // more meaningful than a 24h average dragged down by night-time zeros).
    var WEATHER_META = {
        wind:  { rawField: 'wind_speed',  correctedField: 'wind_speed_corrected',  label: 'Avg Wind Speed', unit: 'm/s',  rawLegend: 'Wind Speed',  correctedLegend: 'Wind Speed (corrected)',  decimals: 1, stat: 'avg' },
        solar: { rawField: 'irradiance',  correctedField: 'irradiance_corrected',  label: 'Max Irradiance', unit: 'W/m²', rawLegend: 'Irradiance', correctedLegend: 'Irradiance (corrected)', decimals: 0, stat: 'max' },
    };

    var RESOLUTION_LABELS = { '1s': '1-Second (multilag)', '1min': '1-Minute', '5min': '5-Minute', 'solar': 'Real-time' };
    var MODEL_LABELS = { wind: 'Wind NED100', solar: 'Solar Photovoltaic (Afrisol)' };

    function formatRunAt(date) {
        return date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
            + ' ' + date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    }

    // ── CSRF helper ───────────────────────────────────────────────────────────
    // ── Export ────────────────────────────────────────────────────────────────
    function onClick(id, handler) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('click', function () { handler(el); });
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

    // ══════════════════════════════════════════════════════════════════════
    // 5-DAY FORECAST
    // ══════════════════════════════════════════════════════════════════════

    var lastApiResponse    = null;
    var lastRunId          = null;  // the stored DtRun behind the shown forecast, if kept
    var lastGenerationType = null;
    var powerChartRoot     = null;
    var chartResetZoomFn   = null;

    // ── Populate results from API data ────────────────────────────────────────
    function populateResults(data, snapshot, runAt) {
        var meta   = WEATHER_META[snapshot.generationType];
        var points = extractPoints(data);

        var now = runAt || new Date();
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

    onClick('chart-reset-zoom-btn', function () {
        if (chartResetZoomFn) chartResetZoomFn();
    });

    onClick('export-json-btn', function (btn) {
        if (!lastApiResponse) return;
        DT.triggerDownload(JSON.stringify(lastApiResponse, null, 2),
            'ciemat-forecast-' + (lastGenerationType || 'result') + '.json', 'application/json');
        DT.flashDownloaded(btn);
    });

    onClick('save-open-jupyterhub-btn', function (btn) {
        if (lastApiResponse) DT.openInJupyterHub(btn, { url: window.CIEMAT_CONFIG.saveResultUrl, source: 'run', id: lastRunId });
    });

    // ══════════════════════════════════════════════════════════════════════
    // COMPARISON OF TWO FORECASTS ("Compare with a second model")
    // ══════════════════════════════════════════════════════════════════════

    var cmChartRoot   = null;
    var cmResetZoomFn = null;
    var cmLastResult  = null;
    var cmRunId       = null;  // the stored DtRun behind the shown comparison, if kept

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

    onClick('cm-reset-zoom-btn', function () {
        if (cmResetZoomFn) cmResetZoomFn();
    });

    onClick('cm-export-json-btn', function (btn) {
        if (!cmLastResult) return;
        DT.triggerDownload(JSON.stringify(cmLastResult, null, 2), 'ciemat-forecast-comparison.json', 'application/json');
        DT.flashDownloaded(btn);
    });

    onClick('cm-save-open-jupyterhub-btn', function (btn) {
        if (cmLastResult) DT.openInJupyterHub(btn, { url: window.CIEMAT_CONFIG.saveResultUrl, source: 'run', id: cmRunId });
    });

    // ══════════════════════════════════════════════════════════════════════
    // REAL-TIME CALCULATION
    // ══════════════════════════════════════════════════════════════════════

    var calcLastResponse = null;

    // `inputs` are the validated parameters the server sent (see ciemat_calculate).
    function populateCalculation(data, inputs, runAt) {
        calcLastResponse = data;
        var isSolar = inputs.resolution === 'solar';
        var powerW  = +data.power_w;
        var powerKw = powerW / 1000;
        document.getElementById('calc-res-model').textContent = isSolar ? 'Solar PV' : 'Wind Power';
        document.getElementById('calc-res-power-kw').textContent = powerKw.toLocaleString(undefined, { maximumFractionDigits: 2 });
        document.getElementById('calc-res-power-w').textContent  = powerW.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' W';
        document.getElementById('calc-res-device').textContent   = inputs.device_id;
        document.getElementById('calc-res-generation-type').textContent = isSolar ? 'Solar PV (Afrisol)' : 'Wind Power (NED100)';
        document.getElementById('calc-res-resolution').textContent = RESOLUTION_LABELS[inputs.resolution] || '—';
        document.getElementById('calc-res-timestamp').textContent = formatRunAt(runAt || new Date());
    }

    onClick('calc-export-json-btn', function (btn) {
        if (!calcLastResponse) return;
        DT.triggerDownload(JSON.stringify(calcLastResponse, null, 2), 'ciemat-calculation-result.json', 'application/json');
        DT.flashDownloaded(btn);
    });

    // ══════════════════════════════════════════════════════════════════════
    // MODEL COMPARATOR
    // ══════════════════════════════════════════════════════════════════════

    var cmpLastResponse  = null;
    var compareChartRoot = null;

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

    onClick('cmp-export-json-btn', function (btn) {
        if (!cmpLastResponse) return;
        DT.triggerDownload(JSON.stringify(cmpLastResponse, null, 2), 'ciemat-model-comparison.json', 'application/json');
        DT.flashDownloaded(btn);
    });

    // ── Entry points ──────────────────────────────────────────────────────────
    // options: { runId: the stored DtRun (for JupyterHub), runAt: when it ran }.
    window.CiematResults = {
        showForecast: function (data, snapshot, options) {
            options = options || {};
            lastRunId          = options.runId || null;
            lastApiResponse    = data;
            lastGenerationType = snapshot.generationType;
            populateResults(data, snapshot, options.runAt);
        },
        // result: { a: {points}, b: {points} }; inputs: { a: {generation_type, ...}, b: ... }.
        showCompareForecasts: function (result, inputs, options) {
            cmLastResult = result;
            cmRunId      = (options || {}).runId || null;
            populateCompareModelsResults(result.a, result.b, inputs.a.generation_type, inputs.b.generation_type);
        },
        showCalculation: function (data, inputs, options) {
            populateCalculation(data, inputs, (options || {}).runAt);
        },
        showCompare: function (data) {
            cmpLastResponse = data;
            populateCompareResults(data.results);
        },
    };

}());
