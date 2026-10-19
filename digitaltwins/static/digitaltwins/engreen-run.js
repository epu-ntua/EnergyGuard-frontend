/* The page of one stored Engreen run: draws it with engreen-results.js, exactly
as the workspace does after a run. */
(function () {
    'use strict';

    var run    = window.ENGREEN_CONFIG.run;
    var inputs = JSON.parse(document.getElementById(run.inputsElementId).textContent);

    // Stations only name the plant and fill its configuration; without them the
    // result is still drawn, with the station id in place of its name.
    var stations = fetch(window.ENGREEN_CONFIG.stationsUrl)
        .then(function (r) { return r.ok ? r.json() : {}; })
        .catch(function () { return {}; });

    DT.loadStoredRun({
        resultUrl: run.resultUrl,
        extras: [stations],
        container: document.getElementById('results-section'),
        show: function (result, extras) {
            window.EngreenResults.setStations(extras[0]);
            window.EngreenResults.show(
                result,
                window.EngreenResults.snapshotFromInputs(run.operation, inputs),
                { runId: run.id, runAt: new Date(run.createdAt) }
            );
        },
    });
}());
