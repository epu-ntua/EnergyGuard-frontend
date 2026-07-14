/* Cookie consent banner configuration (Orest Bida's vanilla-cookieconsent v3).
   Syncs its dark/light appearance with the existing Phoenix theme toggle. */
(function () {
  if (document.documentElement.getAttribute('data-bs-theme') === 'dark') {
    document.documentElement.classList.add('cc--darkmode');
  }

  CookieConsent.run({
    guiOptions: {
      consentModal: {
        layout: 'box inline',
        position: 'bottom right',
        flipButtons: false
      }
    },

    categories: {
      necessary: {
        readOnly: true,
        enabled: true
      }
    },

    language: {
      default: 'en',
      translations: {
        en: {
          consentModal: {
            title: 'We value your privacy',
            description: 'EnergyGuard uses only strictly necessary cookies to keep you signed in and ensure the platform functions correctly. We do not use analytics, tracking or marketing cookies. See our <a href="/static/assets/docs/privacy-policy.pdf" target="_blank" class="cc__link">Privacy Policy</a>.',
            acceptAllBtn: 'Got it',
            // footer: `
            //   <a href="/static/assets/docs/privacy-policy.pdf" target="_blank">Privacy Policy</a>
            //   <a href="/static/assets/docs/terms.pdf" target="_blank">Terms of Service</a>
            // `
          }
        }
      }
    }
  });
})();
