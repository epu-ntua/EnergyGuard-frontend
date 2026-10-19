/* The Engreen workspace: plant and forecast configuration, and running the
forecast. Drawing the result is engreen-results.js (window.EngreenResults). */
(function () {
    'use strict';

    // Set by digitaltwins.runs.services.attach_run_id when the run's result was kept.
    var RUN_ID_HEADER = 'X-DT-Run-Id';

    var Results           = window.EngreenResults;
    var formatStationName = Results.formatStationName;
    var PROFILE_HINT_KEY  = Results.PROFILE_HINT_KEY;

    // ── Station registry (loaded async from /stations API) ───────────────────
    var STATIONS = {};

    function stationLabel(station) {
        return formatStationName(station.name) + ' - ' + station.pnom_kw.toFixed(2) + 'kW';
    }

    // ── Load stations async so page render is not blocked ─────────────────────
    var stationsLoaded = fetch(window.ENGREEN_CONFIG.stationsUrl)
        .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
        .then(function (data) {
            STATIONS = data;
            Results.setStations(data);
            var placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.disabled = true;
            placeholder.selected = true;
            placeholder.textContent = 'Select a station…';
            stationSelect.innerHTML = '';
            stationSelect.appendChild(placeholder);
            Object.keys(data).sort().forEach(function (pod) {
                var opt = document.createElement('option');
                opt.value = pod;
                opt.textContent = stationLabel(data[pod]);
                stationSelect.appendChild(opt);
            });
            stationSelect.disabled = false;
        })
        .catch(function () {
            stationSelect.innerHTML = '<option value="" selected disabled>Could not load stations</option>';
        });

    var PROFILE_API_VALUES = {
        'away':  'away_during_day',
        'mixed': 'mixed_use',
        'home':  'often_home',
    };

    // ── DOM references ────────────────────────────────────────────────────────
    var toggleExisting      = document.getElementById('toggle-existing');
    var toggleNew           = document.getElementById('toggle-new');
    var existingMode        = document.getElementById('existing-station-mode');
    var newMode             = document.getElementById('new-plant-mode');
    var consumptionCard     = document.getElementById('consumption-profile-card');
    var stationSelect       = document.getElementById('station-select');
    var stationDetails      = document.getElementById('station-details');
    var profileLockedNotice = document.getElementById('profile-locked-notice');

    var nPanels             = document.getElementById('n-panels');
    var wpPanel             = document.getElementById('wp-panel');
    var azimuthSlider       = document.getElementById('azimuth-slider');
    var azimuthValue        = document.getElementById('azimuth-value');
    var pnomValue           = document.getElementById('pnom-value');

    var profileCards        = document.querySelectorAll('#consumption-profile-card .dt-tab-card');
    var forecastTypeCards   = document.querySelectorAll('#forecast-type-group .dt-tab-card');
    var forecastDetailPanes = document.querySelectorAll('.forecast-detail-pane');
    var forecastDaysInput   = document.getElementById('forecast-days');

    var runBtn              = document.getElementById('run-forecast-btn');
    var loadingPanel        = document.getElementById('loading-panel');
    var resultsSection      = document.getElementById('results-section');


    // ── State ─────────────────────────────────────────────────────────────────
    var currentMode          = 'existing';
    var selectedProfile      = 'mixed';
    var selectedForecast     = 'short-term';
    var activeController     = null;

    // ── Profile card helpers ──────────────────────────────────────────────────
    function activateProfileCard(key) {
        profileCards.forEach(function (c) {
            var isActive = c.dataset.profile === key;
            c.classList.toggle('active', isActive);
            var chk = c.querySelector('.profile-check');
            if (chk) chk.classList.toggle('invisible', !isActive);
            var radio = c.querySelector('input[type="radio"]');
            if (radio) radio.checked = isActive;
        });
    }

    function syncProfileFromStation() {
        var st = stationSelect.value ? STATIONS[stationSelect.value] : null;
        if (st) {
            activateProfileCard(PROFILE_HINT_KEY[st.profile] || 'mixed');
        } else {
            profileCards.forEach(function (c) {
                c.classList.remove('active');
                var chk = c.querySelector('.profile-check');
                if (chk) chk.classList.add('invisible');
                var radio = c.querySelector('input[type="radio"]');
                if (radio) radio.checked = false;
            });
        }
    }

    // ── Mode toggle ───────────────────────────────────────────────────────────
    function setMode(mode) {
        currentMode = mode;
        if (mode === 'existing') {
            toggleExisting.classList.replace('btn-phoenix-secondary', 'btn-primary');
            toggleNew.classList.replace('btn-primary', 'btn-phoenix-secondary');
            existingMode.classList.remove('d-none');
            newMode.classList.add('d-none');
            consumptionCard.classList.add('profiles-locked');
            profileLockedNotice.classList.remove('d-none');
            syncProfileFromStation();
        } else {
            toggleNew.classList.replace('btn-phoenix-secondary', 'btn-primary');
            toggleExisting.classList.replace('btn-primary', 'btn-phoenix-secondary');
            newMode.classList.remove('d-none');
            existingMode.classList.add('d-none');
            consumptionCard.classList.remove('profiles-locked');
            profileLockedNotice.classList.add('d-none');
            activateProfileCard(selectedProfile);
            newMode.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
                bootstrap.Tooltip.getOrCreateInstance(el);
            });
        }
        validateConfig();
    }

    toggleExisting.addEventListener('click', function () { setMode('existing'); });
    toggleNew.addEventListener('click',      function () { setMode('new'); });

    // ── Station select ────────────────────────────────────────────────────────
    stationSelect.addEventListener('change', function () {
        var data = STATIONS[this.value];
        if (!data) { stationDetails.classList.add('d-none'); syncProfileFromStation(); return; }
        document.getElementById('station-power').textContent   = data.pnom_kw.toFixed(2) + ' kW';
        document.getElementById('station-tilt').textContent    = data.tilt + '°';
        document.getElementById('station-azimuth').textContent = data.azimuth + '° (South)';
        document.getElementById('station-feedin').textContent  = Math.round(data.ratio_feed_in * 100) + '%';
        stationDetails.classList.remove('d-none');
        syncProfileFromStation();
        validateConfig();
    });

    // ── Azimuth slider ────────────────────────────────────────────────────────
    azimuthSlider.addEventListener('input', function () {
        var v = parseInt(this.value, 10);
        azimuthValue.textContent = (v >= 0 ? '+' : '') + v + '°';
    });

    // ── pnom calculation ──────────────────────────────────────────────────────
    function updatePnom() {
        var n  = parseInt(nPanels.value, 10);
        var wp = parseInt(wpPanel.value, 10);
        if (!isNaN(n) && !isNaN(wp) && n > 0 && wp > 0) {
            pnomValue.textContent = (n * wp / 1000).toFixed(2) + ' kW';
        } else {
            pnomValue.textContent = '— kW';
        }
        validateConfig();
    }

    nPanels.addEventListener('input',  updatePnom);
    wpPanel.addEventListener('change', updatePnom);

    // ── Profile cards ─────────────────────────────────────────────────────────
    profileCards.forEach(function (card) {
        card.addEventListener('click', function () {
            activateProfileCard(card.dataset.profile);
            selectedProfile = card.dataset.profile;
        });
    });

    // ── Forecast type cards ───────────────────────────────────────────────────
    forecastTypeCards.forEach(function (card) {
        card.addEventListener('click', function () {
            forecastTypeCards.forEach(function (c) {
                c.classList.remove('active');
                c.setAttribute('aria-pressed', 'false');
            });
            forecastDetailPanes.forEach(function (pane) { pane.classList.add('d-none'); });
            card.classList.add('active');
            card.setAttribute('aria-pressed', 'true');
            selectedForecast = card.dataset.forecast;
            var pane = document.getElementById('detail-' + selectedForecast);
            if (pane) pane.classList.remove('d-none');
            _savePrefs();
        });
        card.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); card.click(); }
        });
    });

    // ── Validation ────────────────────────────────────────────────────────────
    function validateConfig() {
        var valid = false;
        if (currentMode === 'existing') {
            valid = !!stationSelect.value;
        } else {
            var n  = parseInt(nPanels.value, 10);
            var wp = parseInt(wpPanel.value, 10);
            valid = !isNaN(n) && n >= 1 && n <= 50 && !isNaN(wp) && wp > 0;
        }
        runBtn.disabled = !valid;
    }

    // ── Forecast days cap ─────────────────────────────────────────────────────
    forecastDaysInput.addEventListener('input', function () {
        var v = parseInt(this.value, 10);
        if (v > 16) this.value = 16;
        if (v < 1)  this.value = 1;
    });

    // ── CSRF helper ───────────────────────────────────────────────────────────
    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // ── Run Forecast ──────────────────────────────────────────────────────────
    runBtn.addEventListener('click', function () {
        runBtn.disabled = true;
        runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Running…';
        loadingPanel.classList.remove('d-none');
        resultsSection.classList.add('d-none');

        var existingErrorAlert = document.getElementById('forecast-error-alert');
        if (existingErrorAlert) existingErrorAlert.remove();

        var payload = { forecast_type: selectedForecast };
        if (currentMode === 'existing') {
            payload.mode    = 'existing';
            payload.station = stationSelect.value;
        } else {
            payload.mode     = 'new';
            payload.n_panels = parseInt(nPanels.value, 10);
            payload.wp_panel = parseInt(wpPanel.value, 10);
            payload.tilt     = parseInt(document.getElementById('tilt-select').value, 10);
            payload.azimuth  = parseInt(azimuthSlider.value, 10);
            payload.profile  = PROFILE_API_VALUES[selectedProfile] || 'mixed_use';
        }
        if (selectedForecast === 'short-term') {
            payload.days = parseInt(forecastDaysInput.value, 10) || 10;
        }

        // Snapshot UI state before the async call so stale DOM reads can't corrupt results.
        var snapshot = {
            forecastType:    selectedForecast,
            mode:            currentMode,
            stationId:       stationSelect.value,
            selectedProfile: selectedProfile,
            forecastDays:    payload.days || null,
            nPanels:         nPanels.value,
            wpPanel:         wpPanel.value,
            tilt:            document.getElementById('tilt-select').value,
            azimuth:         azimuthSlider.value,
        };

        if (activeController) activeController.abort();
        activeController = new AbortController();
        var signal = activeController.signal;

        fetch(window.ENGREEN_CONFIG.simulateUrl, {
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
                    try { msg = JSON.parse(body).error || msg; } catch (_) {}
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
            Results.show(data, snapshot, { runId: runId });
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
    });

    // ── Initial state ─────────────────────────────────────────────────────────
    setMode('existing');

}());
