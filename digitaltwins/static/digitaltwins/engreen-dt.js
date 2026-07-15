(function () {
    'use strict';

    // ── Station registry (loaded async from /stations API) ───────────────────
    var STATIONS = {};

    function formatStationName(name) {
        return name.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    }

    function stationLabel(station) {
        return formatStationName(station.name) + ' - ' + station.pnom_kw.toFixed(2) + 'kW';
    }

    // ── Load stations async so page render is not blocked ─────────────────────
    fetch(window.ENGREEN_CONFIG.stationsUrl)
        .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
        .then(function (data) {
            STATIONS = data;
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

    var PROFILE_LABELS = {
        'often_home':      'Often Home',
        'mixed_use':       'Mixed Use',
        'away_during_day': 'Away During Day',
    };

    var PROFILE_HINT_KEY = {
        'often_home':      'home',
        'mixed_use':       'mixed',
        'away_during_day': 'away',
    };

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

    var chartGranularity    = document.getElementById('chart-granularity-toggle');
    var chartHourlyBtn      = document.getElementById('chart-hourly-btn');
    var chartDailyBtn       = document.getElementById('chart-daily-btn');

    var exportJsonBtn       = document.getElementById('export-json-btn');
    // var exportCsvBtn        = document.getElementById('export-csv-btn');
    var saveOpenJupyterBtn  = document.getElementById('save-open-jupyterhub-btn');

    // ── State ─────────────────────────────────────────────────────────────────
    var currentMode          = 'existing';
    var selectedProfile      = 'mixed';
    var selectedForecast     = 'short-term';
    var lastApiResponse      = null;
    var lastForecastType     = null;
    var chartGranularityMode = 'hourly';
    var productionChartRoot  = null;
    var chartRefs            = null;
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
            syncGranularityVisibility(selectedForecast);
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

    // ── Granularity toggle visibility ─────────────────────────────────────────
    function syncGranularityVisibility(forecastType) {
        chartGranularity.style.display = forecastType === 'short-term' ? '' : 'none';
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
            granularity:     chartGranularityMode,
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
            return resp.json();
        })
        .then(function (data) {
            activeController = null;
            lastApiResponse  = data;
            lastForecastType = snapshot.forecastType;
            loadingPanel.classList.add('d-none');
            populateResults(data, snapshot);
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

    // ── Populate results from API data ────────────────────────────────────────
    function populateResults(data, snapshot) {
        var forecastLabels = {
            'short-term': 'Short-term forecast',
            'historical':  'Historical baseline',
            'optimistic':  'Optimistic ceiling',
        };
        var profileLabels = {
            'away':  'Away During Day',
            'mixed': 'Mixed Use',
            'home':  'Often Home',
        };

        var now = new Date();
        var ts  = now.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                + ' ' + now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });

        document.getElementById('res-forecast-type').textContent = forecastLabels[snapshot.forecastType] || '—';
        document.getElementById('res-timestamp').textContent     = ts;

        var horizonParts = [];
        if (snapshot.forecastType === 'short-term') {
            horizonParts.push(snapshot.forecastDays + ' days');
            horizonParts.push(snapshot.granularity === 'daily' ? 'Daily' : 'Hourly');
        } else if (snapshot.forecastType === 'historical' || snapshot.forecastType === 'optimistic') {
            horizonParts.push('Annual');
        }
        document.getElementById('res-horizon').textContent = horizonParts.join(' · ') || '—';

        var s = data.summary;
        var isShortTerm = snapshot.forecastType === 'short-term';

        var produced = isShortTerm ? s.produced_kwh       : s.produced_kwh_year;
        var selfCons = isShortTerm ? s.self_consumed_kwh   : s.self_consumed_kwh_year;
        var gridFed  = isShortTerm ? s.fed_in_kwh          : s.fed_in_kwh_year;
        var feedinR  = s.feed_in_ratio;

        document.getElementById('res-pnom').textContent   = s.pnom_kw != null    ? (+s.pnom_kw).toFixed(2)                     : '—';
        document.getElementById('res-total').textContent  = produced  != null    ? (+produced).toLocaleString(undefined, {maximumFractionDigits: 1}) : '—';
        document.getElementById('res-self').textContent   = selfCons  != null    ? (+selfCons).toLocaleString(undefined, {maximumFractionDigits: 1})  : '—';
        document.getElementById('res-grid').textContent   = gridFed   != null    ? (+gridFed).toLocaleString(undefined, {maximumFractionDigits: 1})   : '—';
        document.getElementById('res-feedin').textContent = feedinR   != null    ? Math.round(feedinR * 100)                    : '—';

        if (snapshot.mode === 'existing') {
            var st = STATIONS[snapshot.stationId];
            document.getElementById('res-plant-name').textContent = st
                ? formatStationName(st.name) + ' - ' + (+s.pnom_kw).toFixed(2) + 'kW'
                : snapshot.stationId;
        } else {
            document.getElementById('res-plant-name').textContent =
                'Hypothetical Plant (' + (s.pnom_kw != null ? (+s.pnom_kw).toFixed(2) + ' kW' : '—') + ')';
        }

        // Historical note with real year range
        var histNote = document.getElementById('res-historical-note');
        histNote.classList.toggle('d-none', snapshot.forecastType !== 'historical');
        if (snapshot.forecastType === 'historical' && s.years_averaged && s.years_averaged.length) {
            var yrs = s.years_averaged.slice().sort();
            histNote.querySelector('strong').textContent = yrs[0] + ' – ' + yrs[yrs.length - 1];
        }

        syncGranularityVisibility(snapshot.forecastType);

        // Insights
        var fi = feedinR != null ? Math.round(feedinR * 100) : null;
        document.getElementById('insight-feedin-pct').textContent = fi != null ? fi + '%' : '—';

        var effectiveKey = snapshot.mode === 'existing'
            ? (PROFILE_HINT_KEY[(STATIONS[snapshot.stationId] || {}).profile] || 'mixed')
            : snapshot.selectedProfile;
        var profileHints = {
            'away':  'Increasing daytime consumption may significantly improve self-consumption performance.',
            'mixed': 'Balancing appliance usage during solar peak hours could further reduce grid exports.',
            'home':  'High self-consumption is already achieved. Consider storage to capture evening surplus.',
        };
        document.getElementById('insight-profile-text').textContent = profileHints[effectiveKey] || '';
        document.getElementById('insight-optimistic-row').style.display = 'none';

        // Config summary
        var stSum = snapshot.mode === 'existing' ? STATIONS[snapshot.stationId] : null;
        document.getElementById('sum-mode').textContent            = snapshot.mode === 'existing' ? 'Existing Station' : 'New Plant';
        document.getElementById('sum-panels').textContent          = snapshot.mode === 'new' ? (snapshot.nPanels || '—') : '—';
        document.getElementById('sum-wp').textContent              = snapshot.mode === 'new' ? (snapshot.wpPanel ? snapshot.wpPanel + ' Wp' : '—') : '—';
        document.getElementById('sum-tilt').textContent            = snapshot.mode === 'new' ? (snapshot.tilt + '°') : (stSum ? stSum.tilt + '°' : '—');
        document.getElementById('sum-azimuth').textContent         = snapshot.mode === 'new' ? (snapshot.azimuth + '°') : (stSum ? stSum.azimuth + '° (South)' : '—');
        document.getElementById('sum-profile').textContent         = snapshot.mode === 'new' ? (profileLabels[snapshot.selectedProfile] || '—') : (stSum ? PROFILE_LABELS[stSum.profile] : '(inherited from station)');
        document.getElementById('sum-forecast-type').textContent   = forecastLabels[snapshot.forecastType] || '—';
        document.getElementById('sum-forecast-params').textContent = snapshot.forecastType === 'short-term' ? snapshot.forecastDays + ' days' : 'None';

        renderChart(data, snapshot.forecastType, snapshot.granularity, true);
    }

    // ── Chart rendering ───────────────────────────────────────────────────────
    var MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

    function formatChartLabel(raw) {
        if (/^\d{4}-\d{2}-\d{2}T/.test(raw)) {
            var p = raw.split('T'), d = p[0].split('-');
            return d[2] + ' ' + MONTHS[parseInt(d[1]) - 1] + '\n' + p[1].substring(0, 5);
        }
        var d = raw.split('-');
        if (d.length === 3) return d[2] + ' ' + MONTHS[parseInt(d[1]) - 1];
        return raw;
    }

    function buildChartData(data, forecastType, granularity) {
        if (forecastType === 'short-term') {
            var points = (granularity === 'daily' && data.daily && data.daily.length)
                ? data.daily : (data.hourly || []);
            return points.map(function (p) {
                return {
                    label:        formatChartLabel(p.day || p.timestamp || ''),
                    selfConsumed: +(p.self_consumed_kwh || 0),
                    fedIn:        +(p.fed_in_kwh || 0),
                };
            });
        }
        return (data.monthly || []).map(function (p) {
            return {
                label:        formatChartLabel(p.month || ''),
                selfConsumed: +(p.self_consumed_kwh || 0),
                fedIn:        +(p.fed_in_kwh || 0),
            };
        });
    }

    function renderChart(data, forecastType, granularity, forceRebuild) {
        var placeholder = document.getElementById('chart-placeholder-inner');
        var wrapper     = document.getElementById('chart-canvas-wrapper');
        var chartData   = buildChartData(data, forecastType, granularity);
        var colWidthPct = (forecastType === 'short-term' && granularity === 'daily') ? 50 : 80;

        // Granularity toggle: update axes/series data in-place, no full rebuild.
        if (!forceRebuild && productionChartRoot && chartRefs) {
            chartRefs.xAxis.data.setAll(chartData);
            chartRefs.series.forEach(function (s) {
                s.data.setAll(chartData);
                s.columns.template.set('width', am5.percent(colWidthPct));
            });
            return;
        }

        if (productionChartRoot) {
            productionChartRoot.dispose();
            productionChartRoot = null;
            chartRefs = null;
        }

        placeholder.style.display = 'none';
        wrapper.style.display     = 'block';

        var root = am5.Root.new('production-chart');
        root.setThemes([am5themes_Animated.new(root)]);
        productionChartRoot = root;

        var styles         = getComputedStyle(document.documentElement);
        var textColor      = am5.color(0x31374a);
        var primaryColor   = am5.color(styles.getPropertyValue('--phoenix-primary').trim());
        var turquoiseColor = am5.color(styles.getPropertyValue('--phoenix-turquoise').trim());

        var chart = root.container.children.push(am5xy.XYChart.new(root, {
            layout: root.verticalLayout,
            panX: false,
            panY: false,
            wheelX: 'none',
            wheelY: 'none',
        }));
        chart.zoomOutButton.set('forceHidden', true);

        var xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 50 });
        xRenderer.labels.template.setAll({
            fill: textColor,
            fontSize: 11,
            paddingTop: 6,
            multiLine: true,
            textAlign: 'center',
            oversizedBehavior: 'fit',
        });

        var xAxis = chart.xAxes.push(am5xy.CategoryAxis.new(root, {
            categoryField: 'label',
            renderer: xRenderer,
            tooltip: am5.Tooltip.new(root, {}),
        }));
        xAxis.data.setAll(chartData);

        var yRenderer = am5xy.AxisRendererY.new(root, {});
        yRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, {
            renderer: yRenderer,
            extraMax: 0.05,
        }));
        yAxis.children.unshift(am5.Label.new(root, {
            text: 'kWh',
            rotation: -90,
            y: am5.p50,
            centerX: am5.p50,
            fill: textColor,
            fontSize: 11,
        }));

        chartRefs = { xAxis: xAxis, series: [] };

        function makeSeries(name, field, color, roundTop) {
            var series = chart.series.push(am5xy.ColumnSeries.new(root, {
                name: name,
                xAxis: xAxis,
                yAxis: yAxis,
                valueYField: field,
                categoryXField: 'label',
                stacked: true,
                tooltip: am5.Tooltip.new(root, {
                    labelText: '{name}: {valueY.formatNumber("#,###.###")} kWh',
                }),
            }));
            series.columns.template.setAll({
                fill: color,
                stroke: color,
                strokeOpacity: 0,
                width: am5.percent(colWidthPct),
                cornerRadiusTL: roundTop ? 4 : 0,
                cornerRadiusTR: roundTop ? 4 : 0,
                cornerRadiusBL: roundTop ? 0 : 4,
                cornerRadiusBR: roundTop ? 0 : 4,
            });
            series.data.setAll(chartData);
            series.appear();
            chartRefs.series.push(series);
        }

        makeSeries('Self-consumed', 'selfConsumed', primaryColor,   false);
        makeSeries('Fed into grid', 'fedIn',        turquoiseColor, true);

        chart.set('cursor', am5xy.XYCursor.new(root, { behavior: 'none' }));
        chart.appear(1000, 100);
    }

    // ── Chart granularity toggle ──────────────────────────────────────────────
    chartHourlyBtn.addEventListener('click', function () {
        chartGranularityMode = 'hourly';
        chartHourlyBtn.classList.add('active');
        chartHourlyBtn.classList.replace('btn-phoenix-secondary', 'btn-phoenix-primary');
        chartDailyBtn.classList.remove('active');
        chartDailyBtn.classList.replace('btn-phoenix-primary', 'btn-phoenix-secondary');
        if (lastApiResponse && lastForecastType === 'short-term') {
            renderChart(lastApiResponse, 'short-term', 'hourly');
        }
    });
    chartDailyBtn.addEventListener('click', function () {
        chartGranularityMode = 'daily';
        chartDailyBtn.classList.add('active');
        chartDailyBtn.classList.replace('btn-phoenix-secondary', 'btn-phoenix-primary');
        chartHourlyBtn.classList.remove('active');
        chartHourlyBtn.classList.replace('btn-phoenix-primary', 'btn-phoenix-secondary');
        if (lastApiResponse && lastForecastType === 'short-term') {
            renderChart(lastApiResponse, 'short-term', 'daily');
        }
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
            'pv-forecast-' + (lastForecastType || 'result') + '.json', 'application/json');
        exportJsonBtn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { exportJsonBtn.innerHTML = '<span class="fas fa-file-code me-2"></span>Download Raw Data (JSON)'; }, 2000);
    });

    /*
    exportCsvBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        var header, rows;
        if (lastForecastType === 'short-term') {
            var useHourly = lastApiResponse.hourly && lastApiResponse.hourly.length;
            var points    = useHourly ? lastApiResponse.hourly : (lastApiResponse.daily || []);
            var timeKey   = useHourly ? 'timestamp' : 'day';
            header = [timeKey, 'produced_kwh', 'self_consumed_kwh', 'fed_in_kwh'].join(',');
            rows   = points.map(function (p) {
                return [p[timeKey], p.produced_kwh, p.self_consumed_kwh, p.fed_in_kwh].join(',');
            });
        } else {
            header = 'month,produced_kwh,self_consumed_kwh,fed_in_kwh';
            rows   = (lastApiResponse.monthly || []).map(function (p) {
                return [p.month, p.produced_kwh, p.self_consumed_kwh, p.fed_in_kwh].join(',');
            });
        }
        triggerDownload([header].concat(rows).join('\n'),
            'pv-forecast-' + (lastForecastType || 'result') + '.csv', 'text/csv');
        exportCsvBtn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { exportCsvBtn.innerHTML = '<span class="fas fa-file-csv me-2"></span>Export CSV'; }, 2000);
    });
    */

    saveOpenJupyterBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;

        var originalHtml = saveOpenJupyterBtn.innerHTML;
        saveOpenJupyterBtn.disabled = true;
        saveOpenJupyterBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…';

        fetch(window.ENGREEN_CONFIG.saveResultUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ twin_slug: 'engreen-antrodoco', data: lastApiResponse }),
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

    // ── Initial state ─────────────────────────────────────────────────────────
    setMode('existing');
    syncGranularityVisibility(selectedForecast);

}());
