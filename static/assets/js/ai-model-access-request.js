// Handles "Request access to <model>" forms (deeptsf-detail.html and ai-model-modal.html)
// without navigating away from the page: submits via fetch, then reflects the server's
// actual outcome (never assumes success) in the button state and a toast.
(function () {
  function showToast(success, text) {
    window.EnergyGuardToast.show(
      success ? 'fa-check-circle text-success' : 'fa-exclamation-circle text-danger',
      text
    );
  }

  document.querySelectorAll('.js-ai-model-access-form').forEach(function (form) {
    var button = form.querySelector('button[type="submit"]');
    if (!button) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (button.disabled) return;
      button.disabled = true;

      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then(function (r) {
          return r.json()
            .then(function (data) { return { ok: r.ok, data: data }; })
            .catch(function () { return { ok: false, data: {} }; });
        })
        .then(function (result) {
          var success = result.ok && result.data.success !== false;
          if (success) {
            button.textContent = 'Access requested - awaiting answer';
          } else {
            button.disabled = false;
          }
          showToast(success, result.data.message || (success
            ? 'Your access request has been sent to the admins.'
            : 'Could not send your access request. Please try again later.'));
        })
        .catch(function () {
          button.disabled = false;
          showToast(false, 'Could not send your access request. Please try again later.');
        });
    });
  });
})();
