/* The page of one stored Engreen run: loads its result and draws it with
engreen-results.js, exactly as the workspace does after a run. */
(function () {
    'use strict';

    var run            = window.ENGREEN_CONFIG.run;
    var inputs         = JSON.parse(document.getElementById(run.inputsElementId).textContent);
    var loadingPanel   = document.getElementById('loading-panel');
    var resultsSection = document.getElementById('results-section');

    // Stations only name the plant and fill its configuration; without them the
    // result is still drawn, with the station id in place of its name.
    var stations = fetch(window.ENGREEN_CONFIG.stationsUrl)
        .then(function (r) { return r.ok ? r.json() : {}; })
        .catch(function () { return {}; });

    var result = fetch(run.resultUrl).then(function (r) {
        if (!r.ok) throw new Error('The stored result could not be loaded.');
        return r.json();
    });

    Promise.all([stations, result])
        .then(function (values) {
            window.EngreenResults.setStations(values[0]);
            resultsSection.classList.remove('d-none');
            window.EngreenResults.show(
                values[1],
                window.EngreenResults.snapshotFromInputs(run.operation, inputs),
                { runId: run.id, runAt: new Date(run.createdAt) }
            );
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
