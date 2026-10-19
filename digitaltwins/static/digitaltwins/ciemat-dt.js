/* The CIEMAT workspace: the forms of its three modes and running them. Drawing
the results is ciemat-results.js (window.CiematResults). */
(function () {
    'use strict';

    // Set by digitaltwins.runs.services.attach_run_id when the run's result was kept.
    var RUN_ID_HEADER = 'X-DT-Run-Id';

    var Results = window.CiematResults;

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


    var CEDER_SITE = { lat: 41.68, lon: -2.53 };

    // ── State ─────────────────────────────────────────────────────────────────
    var selectedGeneration   = 'wind';
    var activeController     = null;


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
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            // The site sends no Referer elsewhere (Django's same-origin policy), and OSM's
            // tile servers block requests without one; send just the origin to them.
            referrerPolicy: 'strict-origin-when-cross-origin',
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
            // The stored run's id travels in a header, apart from the service's data.
            // Headers are strings; the export endpoint takes the id as a number.
            var runId = parseInt(resp.headers.get(RUN_ID_HEADER), 10) || null;
            return resp.json().then(function (data) { return { data: data, runId: runId }; });
        })
        .then(function (reply) {
            var data = reply.data, runId = reply.runId;
            activeController = null;
            loadingPanel.classList.add('d-none');
            Results.showForecast(data, snapshot, { runId: runId });
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

    var calcSelectedGeneration = 'wind';
    var calcSelectedResolution = '1s';
    var calcActiveController   = null;

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
            calcLoadingPanel.classList.add('d-none');
            Results.showCalculation(data, payload);

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

    // ══════════════════════════════════════════════════════════════════════
    // MODE 3: MODEL COMPARATOR
    // ══════════════════════════════════════════════════════════════════════

    var cmpRunBtn         = document.getElementById('cmp-run-btn');
    var cmpLoadingPanel   = document.getElementById('cmp-loading-panel');
    var cmpResultsSection = document.getElementById('cmp-results-section');

    var cmpActiveController = null;

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
            cmpLoadingPanel.classList.add('d-none');
            Results.showCompare(data);
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

    // ══════════════════════════════════════════════════════════════════════
    // COMPARE MODE (two independently configured models, integrated into the
    // 5-Day Forecast tab via the "Compare with a second model" toggle above)
    // ══════════════════════════════════════════════════════════════════════

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
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                // The site sends no Referer elsewhere (Django's same-origin policy), and OSM's
                // tile servers block requests without one; send just the origin to them.
                referrerPolicy: 'strict-origin-when-cross-origin',
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

        var inputs = {
            a: { generation_type: modelASelectedGeneration, lat: latA, lon: lonA },
            b: { generation_type: modelBSelectedGeneration, lat: latB, lon: lonB },
        };

        if (activeController) activeController.abort();
        activeController = new AbortController();

        // One request: the server runs both forecasts and records them as one run.
        fetch(window.CIEMAT_CONFIG.compareForecastsUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(inputs),
            signal: activeController.signal,
        })
        .then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (body) {
                    var msg = 'Comparison failed.';
                    try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
                    throw new Error(msg);
                });
            }
            // The stored run's id travels in a header, apart from the service's data.
            // Headers are strings; the export endpoint takes the id as a number.
            var runId = parseInt(resp.headers.get(RUN_ID_HEADER), 10) || null;
            return resp.json().then(function (data) { return { data: data, runId: runId }; });
        })
        .then(function (reply) {
            var data = reply.data, runId = reply.runId;
            activeController = null;
            loadingPanel.classList.add('d-none');
            Results.showCompareForecasts(data, inputs, { runId: runId });
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

}());
