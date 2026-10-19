/* The page of one stored CIEMAT run: loads its result and draws it with
ciemat-results.js, exactly as the workspace does after a run. */
(function () {
    'use strict';

    var run          = window.CIEMAT_CONFIG.run;
    var inputs       = JSON.parse(document.getElementById(run.inputsElementId).textContent);
    var loadingPanel = document.getElementById('loading-panel');
    var runResults   = document.getElementById('run-results');
    var options      = { runId: run.id, runAt: new Date(run.createdAt) };

    // One entry per operation recorded by digitaltwins/ciemat/views.py.
    var SHOW = {
        'forecast': function (result) {
            window.CiematResults.showForecast(result, {
                generationType: inputs.generation_type, lat: inputs.lat, lon: inputs.lon,
            }, options);
        },
        'compare-forecasts': function (result) { window.CiematResults.showCompareForecasts(result, inputs, options); },
        'calculate':         function (result) { window.CiematResults.showCalculation(result, inputs, options); },
        'compare':           function (result) { window.CiematResults.showCompare(result); },
    };

    fetch(run.resultUrl)
        .then(function (r) {
            if (!r.ok) throw new Error('The stored result could not be loaded.');
            return r.json();
        })
        .then(function (result) {
            // Shown before drawing: the charts size themselves from their container.
            runResults.classList.remove('d-none');
            SHOW[run.operation](result);
        })
        .catch(function (err) {
            var alertEl = document.createElement('div');
            alertEl.className = 'alert alert-subtle-danger rounded-3 mb-4';
            alertEl.setAttribute('role', 'alert');
            alertEl.textContent = err.message || 'The stored result could not be loaded.';
            loadingPanel.insertAdjacentElement('afterend', alertEl);
        })
        .finally(function () { loadingPanel.classList.add('d-none'); });
}());
