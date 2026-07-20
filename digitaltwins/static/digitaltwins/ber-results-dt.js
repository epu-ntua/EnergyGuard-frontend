(function () {
    'use strict';

    function readJSON(id) {
        var el = document.getElementById(id);
        return el ? JSON.parse(el.textContent) : {};
    }

    function toChartData(points) {
        return (points || []).map(function (p) {
            return { date: p[0], value: p[1] };
        });
    }

    var powerData      = readJSON('ber-power-data');
    var powerAxis      = readJSON('ber-power-axis');
    var electricalData = readJSON('ber-electrical-data');
    var kpis           = readJSON('ber-kpis');
    var resultMeta     = readJSON('ber-result-meta');

    var rootStyles = getComputedStyle(document.documentElement);
    var textColor  = am5.color(0x31374a);

    function themeColor(varName) {
        return am5.color(rootStyles.getPropertyValue(varName).trim());
    }

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function buildLineChart(containerId, seriesDefs, opts) {
        opts = opts || {};

        var root = am5.Root.new(containerId);
        root.setThemes([am5themes_Animated.new(root)]);

        var chart = root.container.children.push(am5xy.XYChart.new(root, {
            panX: false,
            panY: false,
            wheelX: 'zoomX',
            wheelY: 'none',
            pinchZoomX: true,
            layout: root.verticalLayout,
        }));

        var xRenderer = am5xy.AxisRendererX.new(root, { minGridDistance: 60 });
        xRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var xAxis = chart.xAxes.push(am5xy.DateAxis.new(root, {
            baseInterval: { timeUnit: 'second', count: 1 },
            renderer: xRenderer,
            tooltipDateFormat: 'HH:mm',
            dateFormats: { second: 'HH:mm', minute: 'HH:mm', hour: 'HH:mm', day: 'HH:mm' },
            periodChangeDateFormats: { second: 'HH:mm', minute: 'HH:mm', hour: 'HH:mm', day: 'HH:mm' },
            tooltip: am5.Tooltip.new(root, {}),
        }));

        // Either an inline unit suffix on the tick values ("20 V") or a separate
        // rotated axis title label ("kW") - whichever the caller asked for.
        function labelAxis(axis, unitSuffix, textLabel, rotation, prepend) {
            if (unitSuffix) {
                axis.set('numberFormat', "#,###.# '" + unitSuffix + "'");
                return;
            }
            var label = am5.Label.new(root, {
                text: textLabel || '',
                rotation: rotation,
                y: am5.p50,
                centerX: am5.p50,
                fill: textColor,
                fontSize: 11,
            });
            if (prepend) {
                axis.children.unshift(label);
            } else {
                axis.children.push(label);
            }
        }

        var yRenderer = am5xy.AxisRendererY.new(root, { minGridDistance: opts.yMinGridDistance || 50 });
        yRenderer.labels.template.setAll({ fill: textColor, fontSize: 11 });

        var yAxisSettings = {
            renderer: yRenderer,
            extraMax: opts.yMax != null ? 0 : 0.1,
            extraMin: 0,
        };
        if (opts.yMax != null) {
            yAxisSettings.min = opts.yMin || 0;
            yAxisSettings.max = opts.yMax;
            yAxisSettings.strictMinMax = true;
        }
        var yAxis = chart.yAxes.push(am5xy.ValueAxis.new(root, yAxisSettings));
        labelAxis(yAxis, opts.yUnitSuffix, opts.yLabel, -90, true);

        var yAxis2 = null;
        if (opts.secondAxis) {
            var yRenderer2 = am5xy.AxisRendererY.new(root, { opposite: true });
            yRenderer2.labels.template.setAll({ fill: textColor, fontSize: 11 });
            yAxis2 = chart.yAxes.push(am5xy.ValueAxis.new(root, {
                renderer: yRenderer2,
                extraMax: 0.1,
                extraMin: 0,
            }));
            labelAxis(yAxis2, opts.secondAxis.yUnitSuffix, opts.secondAxis.yLabel, 90, false);
        }

        var seriesList = [];
        seriesDefs.forEach(function (def) {
            var series = chart.series.push(am5xy.LineSeries.new(root, {
                name: def.name,
                xAxis: xAxis,
                yAxis: def.axis === 'right' ? yAxis2 : yAxis,
                valueXField: 'date',
                valueYField: 'value',
                stacked: !!def.stacked,
                stroke: def.color,
                fill: def.color,
                tooltip: am5.Tooltip.new(root, {
                    labelText: '{name}: {valueY.formatNumber("#,###.00")} ' + def.unit,
                }),
            }));
            series.strokes.template.setAll({ strokeWidth: 2 });
            if (def.area) {
                series.fills.template.setAll({ visible: true, fillOpacity: 0.75 });
            } else {
                series.bullets.push(function () {
                    return am5.Bullet.new(root, {
                        sprite: am5.Circle.new(root, {
                            radius: 3,
                            fill: def.color,
                            strokeWidth: 0,
                        }),
                    });
                });
            }
            series.data.setAll(def.data);
            series.appear(600);
            seriesList.push(series);
        });

        var cursor = chart.set('cursor', am5xy.XYCursor.new(root, {
            xAxis: xAxis,
            behavior: 'zoomX',
        }));
        cursor.lineY.set('visible', false);
        cursor.set('snapToSeries', seriesList);

        chart.appear(600, 100);
        return root;
    }

    if (powerData.JT_3002 || powerData.JT_3003) {
        buildLineChart('power-chart', [
            { name: 'Stack power',       data: toChartData(powerData.JT_3002), color: themeColor('--phoenix-primary'),   unit: 'kW', area: true, stacked: true },
            { name: 'Auxiliaries power', data: toChartData(powerData.JT_3003), color: themeColor('--phoenix-turquoise'), unit: 'kW', area: true, stacked: true },
        ], {
            yLabel: 'kW',
            yMinGridDistance: 70,
            yMin: powerAxis.min,
            yMax: powerAxis.max,
        });
    }

    if (electricalData.ET_1001 || electricalData.IT_1101) {
        buildLineChart('electrical-chart', [
            { name: 'Stack voltage', data: toChartData(electricalData.ET_1001), color: themeColor('--phoenix-primary'),   unit: 'V', axis: 'left' },
            { name: 'Stack current', data: toChartData(electricalData.IT_1101), color: themeColor('--phoenix-turquoise'), unit: 'A', axis: 'right' },
        ], { yUnitSuffix: 'V', secondAxis: { yUnitSuffix: 'A' } });
    }

    // ── Save and open in JupyterHub ─────────────────────────────────────────────
    var saveOpenJupyterBtn = document.getElementById('save-open-jupyterhub-btn');
    if (saveOpenJupyterBtn) {
        saveOpenJupyterBtn.addEventListener('click', function () {
            var originalHtml = saveOpenJupyterBtn.innerHTML;
            saveOpenJupyterBtn.disabled = true;
            saveOpenJupyterBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…';

            fetch(window.BER_RESULTS_CONFIG.saveResultUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({
                    twin_slug: 'ber-hydrogen',
                    data: {
                        experiment: resultMeta,
                        kpis: kpis,
                        power: powerData,
                        electrical: electricalData,
                    },
                }),
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
    }

}());
