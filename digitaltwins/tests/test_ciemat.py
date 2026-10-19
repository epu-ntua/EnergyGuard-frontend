"""CIEMAT forecasting DT: forecast, calculate and compare, with the CIEMAT API
faked at `requests.post`."""

import json
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from digitaltwins.models import DtRun

from .fakes import fake_object_storage
from .http_fakes import http_response

User = get_user_model()

WIND = {'device_id': 'WT-1', 'wind_speed': 7.5, 'rpm': 14, 'temperature': 12, 'pitch': 2}
WIND_1S = {**WIND, 'wind_speed_lag_5s': 7.1, 'wind_speed_lag_10s': 6.9, 'wind_speed_lag_20s': 6.5, 'pitch_lag_5s': 2.1}


class CiematTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='ciemat@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)
        # Each run is now recorded with its result in object storage.
        self.storage = self.enterContext(fake_object_storage())

    def post(self, name, body):
        return self.client.post(reverse(name), data=json.dumps(body), content_type='application/json')


class CiematForecastTests(CiematTestCase):
    def test_forecast_proxies_the_points(self):
        points = [{'t': '2026-01-01T00:00:00Z', 'p': 1.5}]
        with patch('requests.post', return_value=http_response(200, points)) as api:
            response = self.post('ciemat-forecast', {'generation_type': 'wind', 'lat': 41.6, 'lon': -2.5})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'points': points})
        self.assertEqual(response['X-DT-Run-Id'], str(DtRun.objects.get(operation='forecast').pk))
        self.assertTrue(api.call_args.args[0].endswith('/api/v1/forecast/wind'))
        self.assertEqual(api.call_args.kwargs['json'], {'lat': 41.6, 'lon': -2.5})
        self.assertIn('X-API-Key', api.call_args.kwargs['headers'])

    def test_invalid_inputs(self):
        for label, body in {
            'generation type': {'generation_type': 'hydro', 'lat': 1, 'lon': 1},
            'missing coordinates': {'generation_type': 'solar'},
            'out of range': {'generation_type': 'solar', 'lat': 91, 'lon': 0},
        }.items():
            with self.subTest(label), patch('requests.post') as api:
                self.assertEqual(self.post('ciemat-forecast', body).status_code, 400)
                api.assert_not_called()

    def test_api_failures_map_to_gateway_errors(self):
        body = {'generation_type': 'solar', 'lat': 40, 'lon': -3}
        for label, effect, status in [
            ('credentials', http_response(401, {}), 502),
            ('rejected input', http_response(422, {}), 422),
            ('server error', http_response(500, {}), 502),
            ('timeout', requests.Timeout(), 504),
            ('unreachable', requests.ConnectionError(), 502),
            ('not json', http_response(200, text='<html>'), 502),
        ]:
            with self.subTest(label):
                kwargs = {'side_effect': effect} if isinstance(effect, Exception) else {'return_value': effect}
                with patch('requests.post', **kwargs):
                    self.assertEqual(self.post('ciemat-forecast', body).status_code, status)


class CiematCalculateTests(CiematTestCase):
    def test_wind_1min(self):
        with patch('requests.post', return_value=http_response(200, 1234.5)) as api:
            response = self.post('ciemat-calculate', {'resolution': '1min', **WIND})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['power_w'], 1234.5)
        self.assertTrue(api.call_args.args[0].endswith('/api/v1/calculate/1min'))
        sent = api.call_args.kwargs['json']
        self.assertEqual(sent['device_id'], 'WT-1')
        self.assertEqual(sent['timestamp'], response.json()['timestamp'])

    def test_solar_sends_its_own_fields(self):
        with patch('requests.post', return_value=http_response(200, 800)) as api:
            self.post('ciemat-calculate', {'resolution': 'solar', 'device_id': 'PV-1', 'radiation': 650, 't_ambiente': 21})

        sent = api.call_args.kwargs['json']
        self.assertEqual((sent['radiation'], sent['T_ambiente']), (650.0, 21.0))

    def test_1s_model_needs_the_lag_values(self):
        with patch('requests.post') as api:
            response = self.post('ciemat-calculate', {'resolution': '1s', **WIND})

        self.assertEqual(response.status_code, 400)
        self.assertIn('1-second model', response.json()['error'])
        api.assert_not_called()

    def test_invalid_inputs(self):
        for label, body in {
            'resolution': {'resolution': '10min', **WIND},
            'device id': {'resolution': '1min', **{**WIND, 'device_id': ' '}},
            'wind values': {'resolution': '5min', 'device_id': 'WT-1', 'wind_speed': 'fast'},
        }.items():
            with self.subTest(label):
                self.assertEqual(self.post('ciemat-calculate', body).status_code, 400)

    def test_non_numeric_answer(self):
        with patch('requests.post', return_value=http_response(200, {'power': 'n/a'})):
            self.assertEqual(self.post('ciemat-calculate', {'resolution': '1min', **WIND}).status_code, 502)


class CiematCompareTests(CiematTestCase):
    def test_runs_all_three_models(self):
        answers = {'1min': 100.0, '5min': 110.0, '1s': 95.0}

        def fake_post(url, **kwargs):
            return http_response(200, answers[url.rsplit('/', 1)[-1]])

        with patch('requests.post', side_effect=fake_post):
            response = self.post('ciemat-compare', WIND_1S)

        self.assertEqual(response.json(), {'results': answers})
        self.assertEqual(response['X-DT-Run-Id'], str(DtRun.objects.get(operation='compare').pk))

    def test_one_failing_model_fails_the_comparison_with_its_name(self):
        def fake_post(url, **kwargs):
            return http_response(500 if url.endswith('/5min') else 200, 100)

        with patch('requests.post', side_effect=fake_post):
            response = self.post('ciemat-compare', WIND_1S)

        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.json()['error'].startswith('5min model:'))


class CiematCompareForecastsTests(CiematTestCase):
    """"Compare with a second model": two forecasts, one request, one recorded run."""

    BODY = {
        'a': {'generation_type': 'wind', 'lat': 41.6, 'lon': -2.5},
        'b': {'generation_type': 'solar', 'lat': 40.4, 'lon': -3.7},
    }

    def test_both_forecasts_are_returned_and_recorded_as_one_run(self):
        def fake_post(url, **kwargs):
            return http_response(200, [{'generation': url.rsplit('/', 1)[1]}])

        with patch('requests.post', side_effect=fake_post) as api:
            response = self.post('ciemat-compare-forecasts', self.BODY)

        self.assertEqual(response.status_code, 200)
        run = DtRun.objects.get()
        self.assertEqual(response.json(), {
            'a': {'points': [{'generation': 'wind'}]},
            'b': {'points': [{'generation': 'solar'}]},
        })
        self.assertEqual(response['X-DT-Run-Id'], str(run.pk))
        self.assertEqual((run.operation, run.inputs), ('compare-forecasts', self.BODY))
        self.assertEqual(api.call_count, 2)

    def test_an_invalid_model_is_named(self):
        body = {**self.BODY, 'b': {'generation_type': 'hydro', 'lat': 1, 'lon': 1}}
        with patch('requests.post') as api:
            response = self.post('ciemat-compare-forecasts', body)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()['error'].startswith('Model B:'))
        api.assert_not_called()

    def test_a_failing_model_records_a_failed_run(self):
        def fake_post(url, **kwargs):
            return http_response(500 if url.endswith('/solar') else 200, [])

        with patch('requests.post', side_effect=fake_post):
            response = self.post('ciemat-compare-forecasts', self.BODY)

        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.json()['error'].startswith('Model B:'))
        self.assertEqual(DtRun.objects.get().status, DtRun.Status.FAILED)


class CiematRunPageTests(CiematTestCase):
    """Each kind of stored run reopens with the partial its results are drawn in."""

    def test_each_operation_renders_its_results(self):
        from digitaltwins.runs.services import record_run

        for operation, inputs, marker in [
            ('forecast', {'generation_type': 'wind', 'lat': 41.6, 'lon': -2.5}, 'id="power-chart"'),
            ('compare-forecasts', {'a': {}, 'b': {}}, 'id="cm-chart"'),
            ('calculate', {'resolution': '1min', 'device_id': 'WT-1'}, 'id="calc-res-power-kw"'),
            ('compare', {'device_id': 'WT-1'}, 'id="compare-chart"'),
        ]:
            with self.subTest(operation):
                run = record_run(user=self.user, twin_slug='ciemat-microgrid', operation=operation,
                                 inputs=inputs, result={})
                response = self.client.get(reverse('ciemat-microgrid-run', args=[run.pk]))
                self.assertContains(response, marker)
                self.assertContains(response, reverse('dt-run-result-data', args=[run.pk]))


class CiematNotConfiguredTests(CiematTestCase):
    @override_settings(CIEMAT_API_KEY='')
    def test_every_endpoint_says_so_without_calling_out(self):
        for name in ['ciemat-forecast', 'ciemat-compare-forecasts', 'ciemat-calculate', 'ciemat-compare']:
            with self.subTest(name), patch('requests.post') as api:
                response = self.post(name, {})
                self.assertEqual(response.status_code, 503)
                api.assert_not_called()
