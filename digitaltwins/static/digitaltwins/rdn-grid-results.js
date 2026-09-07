(function () {
    'use strict';

    var cfg = window.RDN_GRID_RESULTS;
    if (!cfg) return;

    var runningPanel       = document.getElementById('running-panel');
    var elapsedTimeEl      = document.getElementById('elapsed-time');
    var resultsSection     = document.getElementById('results-section');
    var setpointSelector   = document.getElementById('setpoint-selector');
    var busSelector        = document.getElementById('bus-selector');
    var exportJsonBtn      = document.getElementById('export-json-btn');
    var saveOpenJupyterBtn = document.getElementById('save-open-jupyterhub-btn');

    var lastApiResponse = cfg.initialResult;
    var powerChartRoot  = null;
    var freqChartRoot   = null;
    var elapsedTimer    = null;

    // ── CSRF helper ───────────────────────────────────────────────────────────
    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // ── Elapsed ticker (running/pending only) ───────────────────────────────
    function formatElapsed(totalSeconds) {
        var s = Math.max(0, Math.floor(totalSeconds));
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        var sec = s % 60;
        if (h) return h + 'h ' + String(m).padStart(2, '0') + 'm';
        return m + 'm ' + String(sec).padStart(2, '0') + 's';
    }

    var createdAtMs = new Date(cfg.createdAtIso).getTime();
    function tickElapsed() {
        if (elapsedTimeEl) elapsedTimeEl.textContent = formatElapsed((Date.now() - createdAtMs) / 1000);
    }

    // ── Results (selectors) ──────────────────────────────────────────────────
    // Configuration Used (grid section, use case, submitted assets) is rendered
    // server-side from the job itself, which is already known at page load
    // regardless of run status - it never needs updating on poll completion.
    function populateResults() {
        var data = lastApiResponse;

        setpointSelector.innerHTML = '';
        data.outputData.forEach(function (entry, idx) {
            var opt = document.createElement('option');
            opt.value = idx;
            opt.textContent = entry.InputTimestamp_UTC;
            setpointSelector.appendChild(opt);
        });

        populateBusSelector();
        renderCharts();
    }

    function populateBusSelector() {
        var idx = parseInt(setpointSelector.value, 10) || 0;
        var entry = lastApiResponse.outputData[idx];
        var busIds = Object.keys(entry.grid || {}).sort();
        var previousValue = busSelector.value;
        busSelector.innerHTML = '';
        busIds.forEach(function (busId) {
            var opt = document.createElement('option');
            opt.value = busId;
            opt.textContent = busId + ' (' + entry.grid[busId].BusType + ')';
            busSelector.appendChild(opt);
        });
        if (busIds.indexOf(previousValue) !== -1) busSelector.value = previousValue;
    }

    if (setpointSelector) setpointSelector.addEventListener('change', function () { populateBusSelector(); renderCharts(); });
    if (busSelector) busSelector.addEventListener('change', renderCharts);

    // ── Charts (amCharts 5) ───────────────────────────────────────────────────
    function themeColor(varName) {
        var styles = getComputedStyle(document.documentElement);
        return am5.color(styles.getPropertyValue(varName).trim());
    }

    function buildLineChart(containerId, seriesDefs, opts) {
        opts = opts || {};
        var textColor = am5.color(0x31374a);

        var root = am5.Root.new(containerId);
        root.setThemes([am5themes_Animated.new(root)]);

        var chart = root.container.children.push(am5xy.XYChart.new(root, {
            panX: false, panY: false, wheelX: 'zoomX', wheelY: 'none', pinchZoomX: true,
            layout: root.verticalLayout,
        }));

        var xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 60 });
        xRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var xAxis = chart.xAxes.push(am5xy.ValueAxis.new(root, {
            renderer: xRenderer,
            numberFormat: "0.00' s'",
            tooltip: am5.Tooltip.new(root, {}),
        }));

        function labelAxis(axis, unitSuffix, rotation, prepend) {
            axis.set('numberFormat', "#,###.### '" + unitSuffix + "'");
            var label = am5.Label.new(root, {
                text: unitSuffix, rotation: rotation, y: am5.p50, centerX: am5.p50,
                fill: textColor, fontSize: 11,
            });
            if (prepend) axis.children.unshift(label); else axis.children.push(label);
        }

        var yRenderer = am5xy.AxisRendererY.new(root, { minGridDistance: 50 });
        yRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });
        var yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, { renderer: yRenderer, extraMax: 0.1, extraMin: 0.1 }));
        labelAxis(yAxis, opts.yUnit || '', -90, true);

        var yAxis2 = null;
        if (opts.secondAxisUnit) {
            var yRenderer2 = am5xy.AxisRendererY.new(root, { opposite: true });
            yRenderer2.labels.template.setAll({ fill: textColor, fontSize: 11 });
            yAxis2 = chart.yAxes.push(am5xy.ValueAxis.new(root, { renderer: yRenderer2, extraMax: 0.1, extraMin: 0.1 }));
            labelAxis(yAxis2, opts.secondAxisUnit, 90, false);
        }

        var seriesList = [];
        seriesDefs.forEach(function (def) {
            var series = chart.series.push(am5xy.LineSeries.new(root, {
                name: def.name, xAxis: xAxis, yAxis: def.axis === 'right' ? yAxis2 : yAxis,
                valueXField: 't', valueYField: 'value',
                stroke: def.color, fill: def.color,
                tooltip: am5.Tooltip.new(root, { labelText: '{name}: {valueY.formatNumber("#,###.0000")} ' + def.unit }),
            }));
            series.strokes.template.setAll({ strokeWidth: 2 });
            series.data.setAll(def.data);
            series.appear(400);
            seriesList.push(series);
        });

        var cursor = chart.set('cursor', am5xy.XYCursor.new(root, { xAxis: xAxis, behavior: 'zoomX' }));
        cursor.lineY.set('visible', false);
        cursor.set('snapToSeries', seriesList);

        chart.appear(400, 100);
        return root;
    }

    function seriesToChartData(values) {
        return values.map(function (v, k) { return { t: k * 0.002, value: v }; });
    }

    // Instantaneous power per phase is Voltage_kV * Current_kA (= MW); total power
    // at the bus is the sum of the three phases at each timestamp, per RDN's guidance.
    function computeTotalInstantaneousPower(bus) {
        var phases = ['phase_a', 'phase_b', 'phase_c'];
        var length = 0;
        phases.forEach(function (phase) {
            if (bus[phase]) length = Math.max(length, bus[phase].Voltage_kV.length);
        });
        var total = new Array(length).fill(0);
        phases.forEach(function (phase) {
            if (!bus[phase]) return;
            var voltage = bus[phase].Voltage_kV;
            var current = bus[phase].Current_kA;
            var phaseLength = Math.min(voltage.length, current.length);
            for (var k = 0; k < phaseLength; k++) {
                total[k] += voltage[k] * current[k];
            }
        });
        return total;
    }

    function renderCharts() {
        if (!lastApiResponse) return;
        var setpointIdx = parseInt(setpointSelector.value, 10) || 0;
        var entry = lastApiResponse.outputData[setpointIdx];
        var busId = busSelector.value;
        if (!entry || !busId) return;
        var bus = entry.grid[busId];

        if (powerChartRoot) { powerChartRoot.dispose(); powerChartRoot = null; }
        if (bus) {
            powerChartRoot = buildLineChart('power-chart', [
                { name: 'Total power', data: seriesToChartData(computeTotalInstantaneousPower(bus)), color: themeColor('--phoenix-primary'), unit: 'MW' },
            ], { yUnit: 'MW' });
        }

        if (freqChartRoot) { freqChartRoot.dispose(); freqChartRoot = null; }
        if (entry.GridFrequency_Hz) {
            freqChartRoot = buildLineChart('frequency-chart', [
                { name: 'Grid frequency', data: seriesToChartData(entry.GridFrequency_Hz), color: themeColor('--phoenix-primary'), unit: 'Hz' },
            ], { yUnit: 'Hz' });
        }
    }

    // ── Export ────────────────────────────────────────────────────────────────
    function triggerDownload(content, filename, mimeType) {
        var blob = new Blob([content], { type: mimeType });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
    }

    if (exportJsonBtn) {
        exportJsonBtn.addEventListener('click', function () {
            triggerDownload(JSON.stringify(lastApiResponse, null, 2), 'rdn-grid-result-' + lastApiResponse.requestId + '.json', 'application/json');
        });
    }

    if (saveOpenJupyterBtn) {
        saveOpenJupyterBtn.addEventListener('click', function () {
            var originalHtml = saveOpenJupyterBtn.innerHTML;
            saveOpenJupyterBtn.disabled = true;
            saveOpenJupyterBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…';

            fetch(cfg.saveResultUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ twin_slug: 'rdn-grid', data: lastApiResponse }),
            })
            .then(function (resp) {
                if (!resp.ok) {
                    return resp.text().then(function (body) {
                        var msg = 'Could not save the result.';
                        try { msg = JSON.parse(body).error || msg; } catch (_) {}
                        throw new Error(msg);
                    });
                }
                return resp.json();
            })
            .then(function (data) { window.open(data.redirect_url, '_blank'); })
            .catch(function (err) { alert(err.message || 'Could not save the result.'); })
            .finally(function () {
                saveOpenJupyterBtn.disabled = false;
                saveOpenJupyterBtn.innerHTML = originalHtml;
            });
        });
    }

    // ── Poll job status while running/pending ────────────────────────────────
    var POLL_INTERVAL_MS = 10000;

    function completeFromPoll(result) {
        lastApiResponse = result;
        if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
        if (runningPanel) runningPanel.classList.add('d-none');
        if (resultsSection) resultsSection.classList.remove('d-none');
        if (exportJsonBtn) exportJsonBtn.disabled = false;
        if (saveOpenJupyterBtn) saveOpenJupyterBtn.disabled = false;

        var finalDuration = formatElapsed((Date.now() - createdAtMs) / 1000);
        var headerDuration = document.getElementById('duration-label');
        if (headerDuration) headerDuration.textContent = finalDuration;
        var configDuration = document.getElementById('sum-duration');
        if (configDuration) configDuration.textContent = finalDuration;

        populateResults();
    }

    function pollJobStatus() {
        fetch(cfg.jobStatusUrl + '?job=' + encodeURIComponent(cfg.jobId))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === 'completed') {
                    completeFromPoll(data.result);
                    return;
                }
                if (data.status === 'failed') {
                    // Re-render server-side so the failed state (error message + Configuration
                    // Used, from job.assets since there's no result) comes from one source of truth.
                    window.location.reload();
                    return;
                }
                setTimeout(pollJobStatus, POLL_INTERVAL_MS);
            })
            .catch(function () {
                // Transient network blip - keep polling rather than surfacing a spurious error
                // for a job that may still be legitimately running on RDN's side.
                setTimeout(pollJobStatus, POLL_INTERVAL_MS);
            });
    }

    // ── Init ─────────────────────────────────────────────────────────────────
    if (cfg.status === 'completed' && lastApiResponse) {
        populateResults();
    } else if (cfg.status === 'running' || cfg.status === 'pending') {
        tickElapsed();
        elapsedTimer = setInterval(tickElapsed, 1000);
        pollJobStatus();
    }

}());
