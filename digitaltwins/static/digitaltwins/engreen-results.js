/* Drawing an Engreen PV forecast result: KPIs, chart, insights, configuration
summary, and its download / JupyterHub buttons. Shared by the workspace, which
calls show() after a run, and the page reopening a stored run (engreen-run.js).
Expects the markup of digitaltwins/engreen/results.html and window.ENGREEN_CONFIG. */
(function () {
    'use strict';

    // Station registry, from the /stations API: set by the page that loads it.
    var STATIONS = {};

    function formatStationName(name) {
        return name.replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    }

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


    // ── DOM references ────────────────────────────────────────────────────────
    var chartGranularity    = document.getElementById('chart-granularity-toggle');
    var chartHourlyBtn      = document.getElementById('chart-hourly-btn');
    var chartDailyBtn       = document.getElementById('chart-daily-btn');

    var exportJsonBtn       = document.getElementById('export-json-btn');
    // var exportCsvBtn        = document.getElementById('export-csv-btn');
    var saveOpenJupyterBtn  = document.getElementById('save-open-jupyterhub-btn');

    // ── State ─────────────────────────────────────────────────────────────────
    var lastApiResponse      = null;
    var lastRunId            = null;  // the stored DtRun behind the shown result, if kept
    var lastForecastType     = null;
    var chartGranularityMode = 'hourly';
    var productionChartRoot  = null;
    var chartRefs            = null;

    // ── CSRF helper ───────────────────────────────────────────────────────────
    // ── Granularity toggle visibility ─────────────────────────────────────────
    function syncGranularityVisibility(forecastType) {
        chartGranularity.style.display = forecastType === 'short-term' ? '' : 'none';
    }
    // ── Populate results from API data ────────────────────────────────────────
    function populateResults(data, snapshot, runAt) {
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

        var now = runAt || new Date();
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
    exportJsonBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        DT.triggerDownload(JSON.stringify(lastApiResponse, null, 2),
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
        DT.triggerDownload([header].concat(rows).join('\n'),
            'pv-forecast-' + (lastForecastType || 'result') + '.csv', 'text/csv');
        exportCsvBtn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { exportCsvBtn.innerHTML = '<span class="fas fa-file-csv me-2"></span>Export CSV'; }, 2000);
    });
    */

    saveOpenJupyterBtn.addEventListener('click', function () {
        if (!lastApiResponse) return;
        DT.openInJupyterHub(saveOpenJupyterBtn, { url: window.ENGREEN_CONFIG.saveResultUrl, source: 'run', id: lastRunId });
    });
    // The snapshot populateResults expects, rebuilt from a stored run's inputs
    // (the validated parameters the server sent to HAL; see engreen_pv_simulate).
    function snapshotFromInputs(forecastType, inputs) {
        return {
            forecastType:    forecastType,
            mode:            inputs.mode,
            stationId:       inputs.station,
            selectedProfile: PROFILE_HINT_KEY[inputs.profile] || 'mixed',
            forecastDays:    inputs.days || null,
            nPanels:         inputs.n_panels,
            wpPanel:         inputs.wp_panel,
            tilt:            inputs.tilt,
            azimuth:         inputs.azimuth,
        };
    }

    window.EngreenResults = {
        PROFILE_HINT_KEY:   PROFILE_HINT_KEY,
        formatStationName:  formatStationName,
        snapshotFromInputs: snapshotFromInputs,
        setStations: function (stations) { STATIONS = stations || {}; },
        // Draw `data`; options.runId is the stored run (for JupyterHub), options.runAt its time.
        show: function (data, snapshot, options) {
            options = options || {};
            snapshot.granularity = chartGranularityMode;
            lastRunId        = options.runId || null;
            lastApiResponse  = data;
            lastForecastType = snapshot.forecastType;
            populateResults(data, snapshot, options.runAt);
        },
    };

}());
