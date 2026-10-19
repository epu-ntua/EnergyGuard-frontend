"""Browser smoke tests: the twins' pages driven in headless Chromium.

The other tests cover the server; these cover the JavaScript between it and the
user - the forms, the drawing of results, "My runs" and the JupyterHub button.
They run each flow once and fail on any uncaught page error.

Optional: skipped unless Playwright is installed (requirements-dev.txt):

    docker compose exec web pip install -r requirements-dev.txt
    docker compose exec web python -m playwright install --with-deps chromium
    docker compose exec web python manage.py test digitaltwins.tests.test_browser

The pages load amCharts and Leaflet from their CDNs, so the machine needs internet.
External APIs (HAL, CIEMAT, the data-management server) and object storage are
faked in this process, which the live server shares.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from digitaltwins.models import DtExport, DtRun, RdnSimulationJob

from .fakes import fake_object_storage
from .http_fakes import http_response

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dev dependency
    sync_playwright = None

User = get_user_model()

# Playwright's sync API runs an event loop in this thread; the ORM calls the tests
# make between page actions are still plain synchronous code.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

STATION = {'IT001': {'name': 'test_station', 'pnom_kw': 4.0, 'tilt': 30, 'azimuth': 0,
                     'ratio_feed_in': 0.3, 'profile': 'mixed_use'}}


def _hourly(hours=48):
    start = datetime(2026, 10, 20, tzinfo=timezone.utc)
    return [{'timestamp': (start + timedelta(hours=h)).strftime('%Y-%m-%dT%H:%M'),
             'produced_kwh': 1.5, 'self_consumed_kwh': 1.0, 'fed_in_kwh': 0.5} for h in range(hours)]


HAL_SHORT_TERM = {
    'summary': {'pnom_kw': 4.0, 'produced_kwh': 72.0, 'self_consumed_kwh': 48.0,
                'fed_in_kwh': 24.0, 'feed_in_ratio': 0.33},
    'hourly': _hourly(),
    'daily': [{'day': '2026-10-20', 'produced_kwh': 36.0, 'self_consumed_kwh': 24.0, 'fed_in_kwh': 12.0},
              {'day': '2026-10-21', 'produced_kwh': 36.0, 'self_consumed_kwh': 24.0, 'fed_in_kwh': 12.0}],
}


def _forecast_points(power=2.0):
    start = datetime(2026, 10, 20, tzinfo=timezone.utc)
    return [{'timestamp': (start + timedelta(minutes=15 * i)).isoformat(), 'power_kw': power,
             'wind_speed': 7.5, 'irradiance': 300.0, 'temperature': 12.0} for i in range(96)]


def fake_post(url, **kwargs):
    """Every external POST the pages cause: HAL, CIEMAT and the data-management server."""
    if url.startswith(settings.HAL_BASE_URL):
        return http_response(200, HAL_SHORT_TERM)
    if '/forecast/' in url:
        return http_response(200, _forecast_points(2.0 if url.endswith('/wind') else 3.0))
    if '/calculate/' in url:
        return http_response(200, 1250.0)
    if '/provision/user' in url:
        return http_response(200, {})
    raise AssertionError(f'Unexpected POST to {url}')


def fake_get(url, **kwargs):
    if url.startswith(settings.HAL_BASE_URL) and url.endswith('/stations'):
        return http_response(200, STATION)
    raise AssertionError(f'Unexpected GET to {url}')


@unittest.skipIf(sync_playwright is None, 'Playwright is not installed (see requirements-dev.txt)')
# The live server is plain http, and DEBUG is off in tests: no https redirect or
# secure-only cookies here.
@override_settings(SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
                   CIEMAT_API_KEY='test-key', DT_EXPORT_NAME_PREFIX='')
class BrowserSmokeTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(email='browser@example.com', password='pw')
        self.storage = self.enterContext(fake_object_storage())
        self.enterContext(patch('requests.post', side_effect=fake_post))
        self.enterContext(patch('requests.get', side_effect=fake_get))
        # The JupyterHub clean-up is a qcluster task; run it in place.
        self.enterContext(patch('django_q.conf.Conf.SYNC', True))

        self.client.force_login(self.user)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.context.add_cookies([{
            'name': settings.SESSION_COOKIE_NAME,
            'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            'url': self.live_server_url,
        }])
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.page_errors = []
        self.page.on('pageerror', lambda error: self.page_errors.append(error.stack or str(error)))
        # Record what the JupyterHub button opens instead of opening a tab.
        self.page.add_init_script('window.open = function (url) { window.__opened = url; };')

    def tearDown(self):
        self.assertEqual(self.page_errors, [], 'Uncaught errors on the page')

    def open(self, url_name, *args):
        self.page.goto(self.live_server_url + reverse(url_name, args=args))

    def assert_opened_jupyterhub(self, button_selector):
        self.page.click(button_selector)
        self.page.wait_for_function('window.__opened !== undefined')
        self.assertIn('/lab', self.page.evaluate('window.__opened'))

    # ── Engreen ──────────────────────────────────────────────────────────────

    def test_engreen_run_then_reopen_it_from_my_runs(self):
        self.open('engreen-antrodoco-dt')
        self.page.wait_for_selector('#station-select option[value="IT001"]', state='attached')
        self.page.select_option('#station-select', 'IT001')
        # Choosing the forecast type used to throw (an undefined _savePrefs).
        self.page.click('#forecast-type-group [data-forecast="short-term"]')
        self.page.click('#run-forecast-btn')
        self.page.wait_for_selector('#results-section:not(.d-none)')
        self.assertEqual(self.page.inner_text('#res-total'), '72')
        self.page.click('#chart-daily-btn')
        self.assert_opened_jupyterhub('#save-open-jupyterhub-btn')

        run = DtRun.objects.get(user=self.user)
        self.assertEqual(DtExport.objects.get(user=self.user).source_key, run.result_key)

        self.open('dt-runs', 'engreen-antrodoco')
        self.page.click(f'tr[data-run-href] >> text=#{run.pk}')
        self.page.wait_for_url(f'**{reverse("engreen-antrodoco-run", args=[run.pk])}')
        self.page.wait_for_selector('#results-section:not(.d-none)')
        self.assertEqual(self.page.inner_text('#res-total'), '72')

    # ── CIEMAT ───────────────────────────────────────────────────────────────

    def test_ciemat_forecast_and_its_run_page(self):
        self.open('ciemat-forecasting-dt')
        self.page.click('#run-forecast-btn')
        self.page.wait_for_selector('#results-section:not(.d-none)')
        self.assertNotEqual(self.page.inner_text('#res-peak'), '—')
        self.assert_opened_jupyterhub('#save-open-jupyterhub-btn')

        run = DtRun.objects.get(user=self.user, operation='forecast')
        self.open('ciemat-microgrid-run', run.pk)
        self.page.wait_for_selector('#run-results:not(.d-none)')
        self.assertNotEqual(self.page.inner_text('#res-peak'), '—')

    def test_ciemat_comparison_of_two_forecasts(self):
        self.open('ciemat-forecasting-dt')
        self.page.click('#compare-toggle')
        self.page.click('#run-forecast-btn')
        self.page.wait_for_selector('#cm-results-section:not(.d-none)')
        self.assertIn('kWh', self.page.inner_text('#cm-total-a'))
        self.assert_opened_jupyterhub('#cm-save-open-jupyterhub-btn')
        self.assertEqual(DtRun.objects.get(user=self.user).operation, 'compare-forecasts')

    def test_ciemat_calculation_and_model_comparator(self):
        self.open('ciemat-forecasting-dt')
        self.page.click('#mode-calculation-tab')
        self.page.click('#calc-run-btn')
        self.page.wait_for_selector('#calc-results-section:not(.d-none)')
        self.assertEqual(self.page.inner_text('#calc-res-power-kw'), '1.25')

        self.page.click('#mode-compare-tab')
        self.page.click('#cmp-run-btn')
        self.page.wait_for_selector('#cmp-results-section:not(.d-none)')
        self.assertEqual(self.page.inner_text('#cmp-res-1s'), '1.25')

        for operation in ('calculate', 'compare'):
            run = DtRun.objects.get(user=self.user, operation=operation)
            self.open('ciemat-microgrid-run', run.pk)
            self.page.wait_for_selector('#run-results:not(.d-none)')

    # ── Run lists ────────────────────────────────────────────────────────────

    def test_deleting_from_my_runs_asks_first(self):
        from digitaltwins.runs.services import record_run
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='short-term',
                         inputs={'mode': 'existing', 'station': 'IT001', 'days': 2}, result=HAL_SHORT_TERM)

        self.open('dt-runs', 'engreen-antrodoco')
        self.page.click(f'[aria-label="Actions for run #{run.pk}"]')
        self.page.click('.dropdown-menu.show >> text=Delete')
        self.page.wait_for_selector('#dtConfirmModal.show')
        self.assertEqual(self.page.inner_text('#dtConfirmModalLabel'), f'Delete run #{run.pk}')
        self.page.click('#dtConfirmSubmit')
        self.page.wait_for_selector('text=No runs yet.')
        self.assertFalse(DtRun.objects.filter(pk=run.pk).exists())

    def test_rdn_list_download_and_delete(self):
        job = RdnSimulationJob.objects.create(
            user=self.user, use_case='VoltageControl', grid_section='A',
            status=RdnSimulationJob.Status.COMPLETED, result={'requestId': 1},
        )
        RdnSimulationJob.objects.filter(pk=job.pk).update(rdn_request_id=job.pk)

        self.open('rdn-grid-runs')
        self.page.click(f'[aria-label="Actions for run #{job.pk}"]')
        with self.page.expect_download() as download:
            self.page.click('.dropdown-menu.show >> text=Download result')
        self.assertEqual(download.value.suggested_filename, f'rdn-grid-result-{job.pk}.json')

        self.page.click(f'[aria-label="Actions for run #{job.pk}"]')
        self.page.click('.dropdown-menu.show >> text=Delete')
        self.page.wait_for_selector('#dtConfirmModal.show')
        self.page.click('#dtConfirmSubmit')
        self.page.wait_for_selector('text=No runs yet.')
