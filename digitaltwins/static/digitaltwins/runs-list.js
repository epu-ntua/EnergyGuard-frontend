/* Run and request lists of the digital twins: a click anywhere on a row with
data-run-href opens it. Links, buttons and anything inside data-row-ignore (the
actions cell with its dropdown) keep their own behaviour. */
(function () {
    'use strict';

    document.querySelectorAll('[data-run-href]').forEach(function (row) {
        row.addEventListener('click', function (event) {
            if (event.target.closest('[data-row-ignore], a, button, form')) return;
            window.location.href = row.dataset.runHref;
        });
    });
}());
