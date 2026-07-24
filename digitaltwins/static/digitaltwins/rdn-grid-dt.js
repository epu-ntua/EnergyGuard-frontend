(function () {
    'use strict';

    var USE_CASE_LABELS = {};
    document.querySelectorAll('#use-case-select option').forEach(function (option) {
        USE_CASE_LABELS[option.value] = option.textContent.trim();
    });

    // ── DOM references ────────────────────────────────────────────────────────
    var toggleNewRequest    = document.getElementById('toggle-new-request');
    var toggleFollowRequest = document.getElementById('toggle-follow-request');
    var newRequestPanel     = document.getElementById('new-request-panel');
    var followRequestPanel  = document.getElementById('follow-request-panel');

    var useCaseSelect       = document.getElementById('use-case-select');
    var gridSectionSelect   = document.getElementById('grid-section-select');

    var startInput          = document.getElementById('setpoint-start-datetime');
    var resolutionSelect    = document.getElementById('setpoint-resolution-select');
    var customWrapper       = document.getElementById('setpoint-resolution-custom-wrapper');
    var customSecondsInput  = document.getElementById('setpoint-resolution-custom-seconds');
    var countInput          = document.getElementById('setpoint-count');
    var previewList          = document.getElementById('setpoint-preview-list');

    var assetsTableBody     = document.getElementById('assets-table-body');
    var addAssetBtn         = document.getElementById('add-asset-btn');
    var assetsError         = document.getElementById('assets-error');
    var assetRowTemplate    = document.getElementById('asset-row-template');

    var runBtn               = document.getElementById('run-rdn-simulate-btn');

    var followRequestIdInput = document.getElementById('follows-request-id-input');
    var followsLookupBtn     = document.getElementById('follows-lookup-btn');
    var followsNotFound      = document.getElementById('follows-not-found');
    var followsPreview       = document.getElementById('follows-preview');
    var followsGridSection   = document.getElementById('follows-grid-section');
    var followStartInput     = document.getElementById('follow-setpoint-start-datetime');
    var followResolutionSelect = document.getElementById('follow-setpoint-resolution-select');
    var followCustomWrapper  = document.getElementById('follow-setpoint-resolution-custom-wrapper');
    var followCustomSecondsInput = document.getElementById('follow-setpoint-resolution-custom-seconds');
    var followCountInput     = document.getElementById('follow-setpoint-count');
    var followPreviewList    = document.getElementById('follow-setpoint-preview-list');
    var followAssetsTableBody = document.getElementById('follow-assets-table-body');
    var followAssetsError    = document.getElementById('follow-assets-error');
    var runFollowBtn          = document.getElementById('run-rdn-follow-btn');

    var loadingPanel        = document.getElementById('loading-panel');
    var resultsSection      = document.getElementById('results-section');

    var setpointSelector    = document.getElementById('setpoint-selector');
    var busSelector         = document.getElementById('bus-selector');
    var phaseSelect         = document.getElementById('phase-select');

    var exportJsonBtn        = document.getElementById('export-json-btn');
    var exportCsvBtn         = document.getElementById('export-csv-btn');
    var saveOpenJupyterBtn   = document.getElementById('save-open-jupyterhub-btn');

    // ── State ─────────────────────────────────────────────────────────────────
    var selectedUseCase   = useCaseSelect ? useCaseSelect.value : null;
    var setpointTimestamps = [];       // ISO strings, new-request mode
    var followSetpointTimestamps = []; // ISO strings, follow mode
    var followResolved     = null;     // { gridSection, useCase, assets }
    var lastApiResponse    = null;
    var lastRequestMeta    = null;     // { gridSection, useCaseLabel, assets: [{id, type}] }
    var activeController   = null;
    var phaseChartRoot     = null;
    var freqChartRoot      = null;

    // ── CSRF helper ───────────────────────────────────────────────────────────
    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // ── Mode toggle ───────────────────────────────────────────────────────────
    function setMode(mode) {
        if (mode === 'new') {
            toggleNewRequest.classList.replace('btn-phoenix-secondary', 'btn-primary');
            toggleFollowRequest.classList.replace('btn-primary', 'btn-phoenix-secondary');
            newRequestPanel.classList.remove('d-none');
            followRequestPanel.classList.add('d-none');
        } else {
            toggleFollowRequest.classList.replace('btn-phoenix-secondary', 'btn-primary');
            toggleNewRequest.classList.replace('btn-primary', 'btn-phoenix-secondary');
            followRequestPanel.classList.remove('d-none');
            newRequestPanel.classList.add('d-none');
        }
    }
    toggleNewRequest.addEventListener('click', function () { setMode('new'); });
    toggleFollowRequest.addEventListener('click', function () { setMode('follow'); });

    // ── Use case select ───────────────────────────────────────────────────────
    if (useCaseSelect) {
        useCaseSelect.addEventListener('change', function () {
            selectedUseCase = useCaseSelect.value;
        });
    }

    // ── Setpoint timestamp generation ────────────────────────────────────────
    function parseLocalAsUtcMs(str) {
        var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(str || '');
        if (!m) return null;
        return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    }

    function resolutionMs(resolutionSel, customInput) {
        if (resolutionSel.value === 'custom') {
            var secs = parseFloat(customInput.value);
            return (!isNaN(secs) && secs > 0) ? secs * 1000 : null;
        }
        return parseInt(resolutionSel.value, 10);
    }

    function generateTimestamps(startInputEl, resolutionSel, customInput, countInputEl) {
        var startMs = parseLocalAsUtcMs(startInputEl.value);
        var resMs = resolutionMs(resolutionSel, customInput);
        var count = parseInt(countInputEl.value, 10);
        if (startMs == null || !resMs || isNaN(count) || count < 1) return [];
        var out = [];
        for (var i = 0; i < count; i++) {
            out.push(new Date(startMs + i * resMs).toISOString());
        }
        return out;
    }

    function renderPreview(list, previewEl) {
        if (!list.length) {
            previewEl.textContent = 'Set a start time to preview timestamps.';
            return;
        }
        if (list.length <= 6) {
            previewEl.textContent = list.join(', ');
        } else {
            previewEl.textContent = list.slice(0, 5).join(', ') + ' … (+' + (list.length - 6) + ' more) … ' + list[list.length - 1];
        }
    }

    function syncNewSetpoints() {
        setpointTimestamps = generateTimestamps(startInput, resolutionSelect, customSecondsInput, countInput);
        renderPreview(setpointTimestamps, previewList);
        updateAssetHints();
        validateConfig();
    }

    function syncFollowSetpoints() {
        followSetpointTimestamps = generateTimestamps(followStartInput, followResolutionSelect, followCustomSecondsInput, followCountInput);
        renderPreview(followSetpointTimestamps, followPreviewList);
        updateFollowAssetHints();
        validateFollowConfig();
    }

    [startInput, countInput].forEach(function (el) {
        el.addEventListener('input', syncNewSetpoints);
        el.addEventListener('change', syncNewSetpoints);
    });
    resolutionSelect.addEventListener('change', function () {
        customWrapper.classList.toggle('d-none', resolutionSelect.value !== 'custom');
        syncNewSetpoints();
    });
    customSecondsInput.addEventListener('input', syncNewSetpoints);
    customSecondsInput.addEventListener('change', syncNewSetpoints);

    [followStartInput, followCountInput].forEach(function (el) {
        el.addEventListener('input', syncFollowSetpoints);
        el.addEventListener('change', syncFollowSetpoints);
    });
    followResolutionSelect.addEventListener('change', function () {
        followCustomWrapper.classList.toggle('d-none', followResolutionSelect.value !== 'custom');
        syncFollowSetpoints();
    });
    followCustomSecondsInput.addEventListener('input', syncFollowSetpoints);
    followCustomSecondsInput.addEventListener('change', syncFollowSetpoints);

    // ── Asset points parsing/validation ──────────────────────────────────────
    function parseAssetPoints(text, count) {
        var lines = (text || '').split('\n').map(function (l) { return l.trim(); });
        while (lines.length && lines[lines.length - 1] === '') lines.pop();
        if (lines.length !== count) {
            return { ok: false, error: 'Expected ' + count + ' line(s), got ' + lines.length + '.' };
        }
        var points = [];
        for (var i = 0; i < lines.length; i++) {
            var parts = lines[i].split(',').map(function (p) { return p.trim(); });
            if (parts.length < 1 || parts.length > 2) {
                return { ok: false, error: 'Line ' + (i + 1) + ': expected "MW" or "MW,MVAr".' };
            }
            var mw = parts[0] === '' ? undefined : Number(parts[0]);
            var mvar = (parts.length > 1 && parts[1] !== '') ? Number(parts[1]) : undefined;
            if ((mw !== undefined && isNaN(mw)) || (mvar !== undefined && isNaN(mvar))) {
                return { ok: false, error: 'Line ' + (i + 1) + ': values must be numeric.' };
            }
            if (!((mw !== undefined && mw !== 0) || (mvar !== undefined && mvar !== 0))) {
                return { ok: false, error: 'Line ' + (i + 1) + ': at least one non-zero MW or MVAr value is required.' };
            }
            var point = {};
            if (mw !== undefined) point.MW = mw;
            if (mvar !== undefined) point.MVAr = mvar;
            points.push(point);
        }
        return { ok: true, points: points };
    }

    // ── Dynamic asset rows (new request mode) ────────────────────────────────
    function renumberAssetRows() {
        assetsTableBody.querySelectorAll('.rdn-asset-row').forEach(function (row, idx) {
            row.querySelector('.asset-row-label').textContent = 'Asset ' + (idx + 1);
        });
        addAssetBtn.disabled = assetsTableBody.querySelectorAll('.rdn-asset-row').length >= window.RDN_GRID_CONFIG.maxAssets;
    }

    function updateAssetHints() {
        var count = setpointTimestamps.length;
        assetsTableBody.querySelectorAll('.rdn-asset-row').forEach(function (row) {
            row.querySelector('.asset-row-hint').textContent = count
                ? ('Enter exactly ' + count + ' line(s), matching the setpoint timestamps above.')
                : 'Set the setpoint timestamps above first.';
        });
    }

    function addAssetRow() {
        if (assetsTableBody.querySelectorAll('.rdn-asset-row').length >= window.RDN_GRID_CONFIG.maxAssets) return;
        var frag = assetRowTemplate.content.cloneNode(true);
        var row = frag.querySelector('.rdn-asset-row');
        var col = document.createElement('div');
        col.className = 'col-12 col-lg-6';
        col.appendChild(row);
        row.querySelector('.remove-asset-btn').addEventListener('click', function () {
            col.remove();
            renumberAssetRows();
            validateConfig();
        });
        row.querySelector('.asset-type-select').addEventListener('change', validateConfig);
        row.querySelector('.asset-points-textarea').addEventListener('input', validateConfig);
        assetsTableBody.appendChild(col);
        renumberAssetRows();
        updateAssetHints();
        validateConfig();
    }
    addAssetBtn.addEventListener('click', addAssetRow);

    function collectAssets(container, errorEl, count) {
        var rows = container.querySelectorAll('.rdn-asset-row');
        if (!rows.length) {
            errorEl.textContent = 'Add at least one asset.';
            errorEl.classList.remove('d-none');
            return null;
        }
        var assets = {};
        for (var i = 0; i < rows.length; i++) {
            var row = rows[i];
            var typeSelect = row.querySelector('.asset-type-select');
            var typeLabel = row.querySelector('.asset-type-label');
            var assetType = typeSelect ? typeSelect.value : (typeLabel ? typeLabel.dataset.type : '');
            if (!assetType) {
                errorEl.textContent = 'Asset ' + (i + 1) + ': select a bus type.';
                errorEl.classList.remove('d-none');
                return null;
            }
            var parsed = parseAssetPoints(row.querySelector('.asset-points-textarea').value, count);
            if (!parsed.ok) {
                errorEl.textContent = 'Asset ' + (i + 1) + ': ' + parsed.error;
                errorEl.classList.remove('d-none');
                return null;
            }
            var assetId = 'asset_' + String(i + 1).padStart(3, '0');
            assets[assetId] = { assetType: assetType, __points: parsed.points };
        }
        errorEl.classList.add('d-none');
        return assets;
    }

    // ── Validation ────────────────────────────────────────────────────────────
    function validateConfig() {
        assetsError.classList.add('d-none');
        var count = setpointTimestamps.length;
        var valid = !!selectedUseCase && count > 0 && assetsTableBody.querySelectorAll('.rdn-asset-row').length > 0;
        if (valid) {
            var rows = assetsTableBody.querySelectorAll('.rdn-asset-row');
            for (var i = 0; i < rows.length; i++) {
                var typeVal = rows[i].querySelector('.asset-type-select').value;
                var parsed = parseAssetPoints(rows[i].querySelector('.asset-points-textarea').value, count);
                if (!typeVal || !parsed.ok) { valid = false; break; }
            }
        }
        runBtn.disabled = !valid;
    }

    function validateFollowConfig() {
        followAssetsError.classList.add('d-none');
        var count = followSetpointTimestamps.length;
        if (!followResolved || count === 0) { runFollowBtn.disabled = true; return; }
        var rows = followAssetsTableBody.querySelectorAll('.rdn-asset-row');
        var valid = rows.length > 0;
        rows.forEach(function (row) {
            var parsed = parseAssetPoints(row.querySelector('.asset-points-textarea').value, count);
            if (!parsed.ok) valid = false;
        });
        runFollowBtn.disabled = !valid;
    }

    function updateFollowAssetHints() {
        var count = followSetpointTimestamps.length;
        followAssetsTableBody.querySelectorAll('.rdn-asset-row').forEach(function (row) {
            row.querySelector('.asset-row-hint').textContent = count
                ? ('Enter exactly ' + count + ' line(s), matching the setpoint timestamps above.')
                : 'Set the setpoint timestamps above first.';
        });
    }

    // ── Follow lookup ─────────────────────────────────────────────────────────
    followsLookupBtn.addEventListener('click', function () {
        var requestId = parseInt(followRequestIdInput.value, 10);
        followsNotFound.classList.add('d-none');
        followsPreview.classList.add('d-none');
        followResolved = null;
        runFollowBtn.disabled = true;
        if (isNaN(requestId) || requestId < 1) return;

        fetch(window.RDN_GRID_CONFIG.followLookupUrl + '?requestId=' + encodeURIComponent(requestId))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.found) {
                    followsNotFound.classList.remove('d-none');
                    return;
                }
                followResolved = data;
                followsGridSection.textContent = data.gridSection;
                followAssetsTableBody.innerHTML = '';
                Object.keys(data.assets).sort().forEach(function (assetId) {
                    var frag = assetRowTemplate.content.cloneNode(true);
                    var row = frag.querySelector('.rdn-asset-row');
                    row.querySelector('.asset-row-label').textContent = assetId + ' (' + data.assets[assetId] + ')';
                    var typeSelectEl = row.querySelector('.asset-type-select');
                    typeSelectEl.remove();
                    var typeLabel = document.createElement('span');
                    typeLabel.className = 'badge bg-primary-subtle text-primary asset-type-label';
                    typeLabel.dataset.type = data.assets[assetId];
                    typeLabel.textContent = data.assets[assetId];
                    row.querySelector('.col-12.col-md-3').appendChild(typeLabel);
                    row.dataset.assetId = assetId;
                    row.querySelector('.asset-points-textarea').addEventListener('input', validateFollowConfig);
                    followAssetsTableBody.appendChild(row);
                });
                followsPreview.classList.remove('d-none');
                updateFollowAssetHints();
                validateFollowConfig();
            })
            .catch(function () {
                followsNotFound.classList.remove('d-none');
            });
    });

    // ── Run simulation (shared by both modes) ────────────────────────────────
    function runningState(btn, isRunning) {
        btn.disabled = isRunning;
        btn.innerHTML = isRunning
            ? '<span class="spinner-border spinner-border-sm me-2"></span>Running…'
            : 'Run simulation &rarr;';
    }

    function showRunError(message) {
        var existing = document.getElementById('rdn-error-alert');
        if (existing) existing.remove();
        var alertEl = document.createElement('div');
        alertEl.id = 'rdn-error-alert';
        alertEl.className = 'alert alert-subtle-danger rounded-3 mb-4 d-flex align-items-center gap-2';
        alertEl.setAttribute('role', 'alert');
        alertEl.innerHTML = '<span class="fas fa-circle-xmark flex-shrink-0"></span><span></span>';
        alertEl.querySelector('span:last-child').textContent = message || 'An unexpected error occurred. Please try again.';
        loadingPanel.insertAdjacentElement('afterend', alertEl);
        setTimeout(function () { if (alertEl.parentNode) alertEl.remove(); }, 8000);
    }

    function submitRequest(payload, meta, btn) {
        runningState(btn, true);
        loadingPanel.classList.remove('d-none');
        resultsSection.classList.add('d-none');
        var existingErrorAlert = document.getElementById('rdn-error-alert');
        if (existingErrorAlert) existingErrorAlert.remove();

        if (activeController) activeController.abort();
        activeController = new AbortController();

        fetch(window.RDN_GRID_CONFIG.simulateUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(payload),
            signal: activeController.signal,
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Simulation failed.';
                    try { msg = JSON.parse(body).error || msg; } catch (_) {}
                    throw new Error(msg);
                });
            }
            return resp.json();
        })
        .then(function (data) {
            activeController = null;
            lastApiResponse = data;
            lastRequestMeta = meta;
            loadingPanel.classList.add('d-none');
            runningState(btn, false);
            populateResults();
            resultsSection.classList.remove('d-none');
            resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        })
        .catch(function (err) {
            if (err.name === 'AbortError') return;
            activeController = null;
            loadingPanel.classList.add('d-none');
            runningState(btn, false);
            showRunError(err.message);
        });
    }

    runBtn.addEventListener('click', function () {
        var assets = collectAssets(assetsTableBody, assetsError, setpointTimestamps.length);
        if (!assets) return;

        var assetInput = {};
        var assetsMeta = [];
        Object.keys(assets).forEach(function (assetId) {
            assetInput[assetId] = {
                assetType: assets[assetId].assetType,
                assetTimeSeries: setpointTimestamps.map(function (ts, idx) {
                    return Object.assign({ timestamp_UTC: ts }, assets[assetId].__points[idx]);
                }),
            };
            assetsMeta.push({ id: assetId, type: assets[assetId].assetType });
        });

        var requestId = Date.now();
        var payload = {
            userId: window.RDN_GRID_CONFIG.userId,
            userOrganisation: window.RDN_GRID_CONFIG.userOrganisation,
            useCase: selectedUseCase,
            requestId: requestId,
            requestTimestamp_UTC: new Date().toISOString(),
            inputData: {
                gridSection: gridSectionSelect.value,
                asset: assetInput,
            },
        };
        submitRequest(payload, {
            gridSection: gridSectionSelect.value,
            useCaseLabel: USE_CASE_LABELS[selectedUseCase] || selectedUseCase,
            assets: assetsMeta,
        }, runBtn);
    });

    runFollowBtn.addEventListener('click', function () {
        if (!followResolved) return;
        var assets = collectAssets(followAssetsTableBody, followAssetsError, followSetpointTimestamps.length);
        if (!assets) return;

        var assetInput = {};
        var assetsMeta = [];
        // collectAssets() assigns fresh asset_001... ids in DOM order; re-key them onto
        // the real resolved asset ids, which were used to build the rows in that same order.
        var resolvedIds = Object.keys(followResolved.assets).sort();
        var collectedList = Object.keys(assets);
        resolvedIds.forEach(function (assetId, i) {
            var collected = assets[collectedList[i]];
            assetInput[assetId] = {
                assetType: followResolved.assets[assetId],
                assetTimeSeries: followSetpointTimestamps.map(function (ts, idx) {
                    return Object.assign({ timestamp_UTC: ts }, collected.__points[idx]);
                }),
            };
            assetsMeta.push({ id: assetId, type: followResolved.assets[assetId] });
        });

        var requestId = Date.now();
        var payload = {
            userId: window.RDN_GRID_CONFIG.userId,
            userOrganisation: window.RDN_GRID_CONFIG.userOrganisation,
            useCase: followResolved.useCase,
            requestId: requestId,
            requestTimestamp_UTC: new Date().toISOString(),
            followsRequestId: parseInt(followRequestIdInput.value, 10),
            inputData: {
                gridSection: followResolved.gridSection,
                asset: assetInput,
            },
        };
        submitRequest(payload, {
            gridSection: followResolved.gridSection,
            useCaseLabel: USE_CASE_LABELS[followResolved.useCase] || followResolved.useCase,
            assets: assetsMeta,
        }, runFollowBtn);
    });

    // ── Results ───────────────────────────────────────────────────────────────
    function populateResults() {
        var data = lastApiResponse;
        var meta = lastRequestMeta;

        document.getElementById('res-request-id').textContent = data.requestId;

        var now = new Date();
        document.getElementById('res-timestamp').textContent =
            now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
            + ' ' + now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

        document.getElementById('sum-grid-section').textContent = meta.gridSection;
        document.getElementById('sum-use-case').textContent = meta.useCaseLabel;
        document.getElementById('sum-assets-list').textContent = meta.assets.map(function (a) {
            return a.id + ' (' + a.type + ')';
        }).join(', ');

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

    setpointSelector.addEventListener('change', function () { populateBusSelector(); renderCharts(); });
    busSelector.addEventListener('change', renderCharts);
    phaseSelect.addEventListener('change', renderCharts);

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

    function renderCharts() {
        if (!lastApiResponse) return;
        var setpointIdx = parseInt(setpointSelector.value, 10) || 0;
        var entry = lastApiResponse.outputData[setpointIdx];
        var busId = busSelector.value;
        var phase = phaseSelect.value;
        if (!entry || !busId) return;
        var bus = entry.grid[busId];

        if (phaseChartRoot) { phaseChartRoot.dispose(); phaseChartRoot = null; }
        if (bus && bus[phase]) {
            phaseChartRoot = buildLineChart('phase-chart', [
                { name: 'Voltage', data: seriesToChartData(bus[phase].Voltage_kV), color: themeColor('--phoenix-primary'), unit: 'kV', axis: 'left' },
                { name: 'Current', data: seriesToChartData(bus[phase].Current_kA), color: themeColor('--phoenix-turquoise'), unit: 'kA', axis: 'right' },
            ], { yUnit: 'kV', secondAxisUnit: 'kA' });
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

    exportJsonBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        triggerDownload(JSON.stringify(lastApiResponse, null, 2), 'rdn-grid-result-' + lastApiResponse.requestId + '.json', 'application/json');
    });

    exportCsvBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        var rows = ['setpoint_ts,bus_id,bus_type,phase,sample_index,offset_ms,Voltage_kV,Current_kA,GridFrequency_Hz'];
        lastApiResponse.outputData.forEach(function (entry) {
            var freq = entry.GridFrequency_Hz || [];
            Object.keys(entry.grid || {}).sort().forEach(function (busId) {
                var bus = entry.grid[busId];
                ['phase_a', 'phase_b', 'phase_c'].forEach(function (phase) {
                    if (!bus[phase]) return;
                    bus[phase].Voltage_kV.forEach(function (v, k) {
                        var i = bus[phase].Current_kA[k];
                        var f = freq[k] != null ? freq[k] : '';
                        rows.push([entry.InputTimestamp_UTC, busId, bus.BusType, phase, k, k * 2, v, i, f].join(','));
                    });
                });
            });
        });
        triggerDownload(rows.join('\n'), 'rdn-grid-result-' + lastApiResponse.requestId + '.csv', 'text/csv');
    });

    saveOpenJupyterBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        var originalHtml = saveOpenJupyterBtn.innerHTML;
        saveOpenJupyterBtn.disabled = true;
        saveOpenJupyterBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…';

        fetch(window.RDN_GRID_CONFIG.saveResultUrl, {
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

    // ── Initial state ─────────────────────────────────────────────────────────
    setMode('new');
    addAssetRow();

    if (startInput && !startInput.value) {
        var pad = function (n) { return String(n).padStart(2, '0'); };
        var now = new Date();
        startInput.value = now.getUTCFullYear() + '-' + pad(now.getUTCMonth() + 1) + '-' + pad(now.getUTCDate()) + 'T' + pad(now.getUTCHours()) + ':' + pad(now.getUTCMinutes());
        syncNewSetpoints();
    }

}());
