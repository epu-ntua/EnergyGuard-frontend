/* Helpers shared by the digital twins' pages (window.DT). Loaded before each
twin's own scripts. Expects <meta name="csrf-token"> in the page head. */
(function () {
    'use strict';

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function triggerDownload(content, filename, mimeType) {
        var blob = new Blob([content], { type: mimeType });
        var url  = URL.createObjectURL(blob);
        var a    = document.createElement('a');
        a.href = url; a.download = filename; a.click();
        URL.revokeObjectURL(url);
    }

    function flashDownloaded(btn) {
        var originalHtml = btn.innerHTML;
        btn.innerHTML = '<span class="fas fa-check me-2"></span>Downloaded';
        setTimeout(function () { btn.innerHTML = originalHtml; }, 2000);
    }

    // A rejected promise carrying the server's {"error": ...} message, or `fallback`.
    function errorFrom(resp, fallback) {
        return resp.text().then(function (body) {
            var msg = fallback;
            try { msg = JSON.parse(body).error || msg; } catch (parseErr) { console.error('Could not parse error response body:', parseErr); }
            throw new Error(msg);
        });
    }

    /* Ask the server to copy a stored result into JupyterHub, then open it.
       options: { url: the dt-save-result URL, source: 'run' | 'rdn' | 'ber', id: number }.
       The server only takes ids as numbers - a header value must be parsed first. */
    function openInJupyterHub(btn, options) {
        if (!options.id) {
            alert('This result was not kept, so it cannot be opened in JupyterHub. Please run it again.');
            return;
        }

        var originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving…';

        fetch(options.url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ source: options.source, id: options.id }),
        })
        .then(function (resp) {
            return resp.ok ? resp.json() : errorFrom(resp, 'Could not save the result.');
        })
        .then(function (data) { window.open(data.redirect_url, '_blank'); })
        .catch(function (err) { alert(err.message || 'Could not save the result.'); })
        .finally(function () {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        });
    }

    /* The page of one stored run: fetch its result (and anything else it needs,
       as `extras` promises), show the results container, then draw.
       options: { resultUrl, extras: [promises], container: element, show(result, extraValues) }.
       Expects #loading-panel, hidden once done or failed. */
    function loadStoredRun(options) {
        var loadingPanel = document.getElementById('loading-panel');
        var result = fetch(options.resultUrl).then(function (r) {
            if (!r.ok) throw new Error('The stored result could not be loaded.');
            return r.json();
        });

        Promise.all([result].concat(options.extras || []))
            .then(function (values) {
                // Shown before drawing: the charts size themselves from their container.
                options.container.classList.remove('d-none');
                options.show(values[0], values.slice(1));
            })
            .catch(function (err) {
                var alertEl = document.createElement('div');
                alertEl.className = 'alert alert-subtle-danger rounded-3 mb-4';
                alertEl.setAttribute('role', 'alert');
                alertEl.textContent = err.message || 'The stored result could not be loaded.';
                loadingPanel.insertAdjacentElement('afterend', alertEl);
            })
            .finally(function () { loadingPanel.classList.add('d-none'); });
    }

    window.DT = {
        getCsrfToken: getCsrfToken,
        triggerDownload: triggerDownload,
        flashDownloaded: flashDownloaded,
        errorFrom: errorFrom,
        openInJupyterHub: openInJupyterHub,
        loadStoredRun: loadStoredRun,
    };
}());
