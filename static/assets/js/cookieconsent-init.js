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
      },
      preferencesModal: {
        layout: 'box'
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
          },
          // Opened by the "Cookie preferences" button in the profile's Privacy tab.
          // There is only the read-only necessary category, so it informs rather than asks.
          preferencesModal: {
            title: 'Cookie preferences',
            acceptAllBtn: 'Got it',
            closeIconLabel: 'Close',
            sections: [
              {
                description: 'EnergyGuard uses only the cookies it needs to keep you signed in and to protect your session. There are no analytics, tracking or marketing cookies, so there is nothing to switch off.'
              },
              {
                title: 'Strictly necessary cookies <span class="pm__badge">Always enabled</span>',
                description: 'These cookies are required for the platform to work and cannot be disabled.',
                linkedCategory: 'necessary',
                cookieTable: {
                  headers: {
                    name: 'Cookie',
                    domain: 'Set by',
                    desc: 'Purpose',
                    exp: 'Expires'
                  },
                  body: [
                    { name: 'sessionid', domain: 'EnergyGuard', desc: 'Keeps you signed in to the platform.', exp: '30 minutes' },
                    { name: 'csrftoken', domain: 'EnergyGuard', desc: 'Protects forms against cross-site request forgery.', exp: '1 year' },
                    { name: 'cc_cookie', domain: 'EnergyGuard', desc: 'Remembers that you have seen this cookie notice.', exp: '6 months' },
                    { name: 'KEYCLOAK_*, AUTH_SESSION_ID', domain: 'EnergyGuard sign-in (Keycloak)', desc: 'Keep your single sign-on session.', exp: 'End of the sign-in session' }
                  ]
                }
              },
              {
                title: 'More information',
                description: 'See our <a href="/static/assets/docs/privacy-policy.pdf" target="_blank" class="cc__link">Privacy Policy</a> for details on how we process your data.'
              }
            ]
          }
        }
      }
    }
  });
})();
