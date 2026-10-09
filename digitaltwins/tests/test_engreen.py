from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

User = get_user_model()


class EngreenPvSimulateTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='pass')
        self.client.force_login(self.user)
        self.url = reverse('engreen-pv-simulate')

    def _post(self, payload):
        return self.client.post(
            self.url, data=payload, content_type='application/json'
        )

    # ── Auth ──────────────────────────────────────────────────────────────────

    def test_requires_login(self):
        self.client.logout()
        resp = self._post({'mode': 'existing', 'forecast_type': 'short-term', 'station': 'X'})
        self.assertIn(resp.status_code, (302, 403))

    def test_requires_post(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    # ── forecast_type validation ──────────────────────────────────────────────

    def test_invalid_forecast_type(self):
        resp = self._post({'mode': 'existing', 'forecast_type': 'bad', 'station': 'X'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_missing_forecast_type(self):
        resp = self._post({'mode': 'existing', 'station': 'X'})
        self.assertEqual(resp.status_code, 400)

    # ── mode=existing validation ──────────────────────────────────────────────

    def test_existing_mode_missing_station(self):
        resp = self._post({'mode': 'existing', 'forecast_type': 'short-term', 'station': ''})
        self.assertEqual(resp.status_code, 400)

    def test_existing_mode_no_station_key(self):
        resp = self._post({'mode': 'existing', 'forecast_type': 'short-term'})
        self.assertEqual(resp.status_code, 400)

    # ── mode=new validation ───────────────────────────────────────────────────

    def test_new_mode_n_panels_too_low(self):
        resp = self._post({
            'mode': 'new', 'forecast_type': 'short-term',
            'n_panels': 0, 'wp_panel': 400, 'tilt': 30, 'azimuth': 0,
            'profile': 'mixed_use',
        })
        self.assertEqual(resp.status_code, 400)

    def test_new_mode_n_panels_too_high(self):
        resp = self._post({
            'mode': 'new', 'forecast_type': 'short-term',
            'n_panels': 51, 'wp_panel': 400, 'tilt': 30, 'azimuth': 0,
            'profile': 'mixed_use',
        })
        self.assertEqual(resp.status_code, 400)

    def test_new_mode_invalid_profile(self):
        resp = self._post({
            'mode': 'new', 'forecast_type': 'short-term',
            'n_panels': 10, 'wp_panel': 400, 'tilt': 30, 'azimuth': 0,
            'profile': 'invalid_profile',
        })
        self.assertEqual(resp.status_code, 400)

    def test_new_mode_missing_params(self):
        resp = self._post({
            'mode': 'new', 'forecast_type': 'short-term',
            'profile': 'mixed_use',
            # n_panels, wp_panel, tilt, azimuth missing
        })
        self.assertEqual(resp.status_code, 400)

    # ── invalid mode ──────────────────────────────────────────────────────────

    def test_invalid_mode(self):
        resp = self._post({'mode': 'unknown', 'forecast_type': 'short-term'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_mode(self):
        resp = self._post({'forecast_type': 'short-term', 'station': 'X'})
        self.assertEqual(resp.status_code, 400)

    # ── invalid JSON body ─────────────────────────────────────────────────────

    def test_invalid_json_body(self):
        resp = self.client.post(self.url, data='not json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    # ── rate limiting ─────────────────────────────────────────────────────────

    def test_rate_limit_blocks_after_limit(self):
        from django.core.cache import cache
        from digitaltwins.views import _SIMULATE_RATE_LIMIT, _SIMULATE_RATE_WINDOW
        key = f'engreen_simulate_rl_{self.user.pk}'
        cache.set(key, _SIMULATE_RATE_LIMIT, timeout=_SIMULATE_RATE_WINDOW)
        resp = self._post({
            'mode': 'existing', 'forecast_type': 'short-term', 'station': 'X'
        })
        self.assertEqual(resp.status_code, 429)
        cache.delete(key)

    # ── HAL proxy (happy path) ────────────────────────────────────────────────

    @patch('digitaltwins.views.requests.post')
    def test_existing_mode_short_term_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'summary': {}, 'hourly': []}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        resp = self._post({
            'mode': 'existing', 'forecast_type': 'short-term',
            'station': 'IT001E61366665', 'days': 7,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('summary', resp.json())

    @patch('digitaltwins.views.requests.post')
    def test_new_mode_historical_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'summary': {}, 'monthly': []}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        resp = self._post({
            'mode': 'new', 'forecast_type': 'historical',
            'n_panels': 10, 'wp_panel': 400, 'tilt': 30, 'azimuth': 0,
            'profile': 'mixed_use',
        })
        self.assertEqual(resp.status_code, 200)

    @patch('digitaltwins.views.requests.post')
    def test_hal_timeout_returns_504(self, mock_post):
        import requests as req_lib
        mock_post.side_effect = req_lib.Timeout()

        resp = self._post({
            'mode': 'existing', 'forecast_type': 'short-term',
            'station': 'IT001E61366665', 'days': 7,
        })
        self.assertEqual(resp.status_code, 504)

    @patch('digitaltwins.views.requests.post')
    def test_hal_5xx_returns_502(self, mock_post):
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.side_effect = req_lib.HTTPError(response=mock_resp)

        resp = self._post({
            'mode': 'existing', 'forecast_type': 'short-term',
            'station': 'IT001E61366665', 'days': 7,
        })
        self.assertEqual(resp.status_code, 502)

    @patch('digitaltwins.views.requests.post')
    def test_hal_4xx_returns_422(self, mock_post):
        import requests as req_lib
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_post.side_effect = req_lib.HTTPError(response=mock_resp)

        resp = self._post({
            'mode': 'existing', 'forecast_type': 'short-term',
            'station': 'IT001E61366665', 'days': 7,
        })
        self.assertEqual(resp.status_code, 422)
