/* The page of one stored CIEMAT run: draws it with ciemat-results.js, exactly
as the workspace does after a run. */
(function () {
    'use strict';

    var run     = window.CIEMAT_CONFIG.run;
    var inputs  = JSON.parse(document.getElementById(run.inputsElementId).textContent);
    var options = { runId: run.id, runAt: new Date(run.createdAt) };

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

    DT.loadStoredRun({
        resultUrl: run.resultUrl,
        container: document.getElementById('run-results'),
        show: SHOW[run.operation],
    });
}());
