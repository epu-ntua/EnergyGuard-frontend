"""Riga buildings API, Engreen stations, and saving a twin's result to JupyterHub."""

import json
from unittest.mock import patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from digitaltwins.models import DtResult

from .fakes import fake_object_storage
from .http_fakes import http_response

User = get_user_model()


class RigaBuildingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='riga@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)

    def _buildings(self, **bbox):
        return self.client.get(reverse('rea-riga-buildings-api'), bbox)

    def test_bbox_filters_the_buildings(self):
        everything = self._buildings(min_lon=-180, min_lat=-90, max_lon=180, max_lat=90).json()
        nothing = self._buildings(min_lon=0, min_lat=0, max_lon=0.001, max_lat=0.001).json()

        self.assertEqual(everything['type'], 'FeatureCollection')
        self.assertGreater(len(everything['features']), 0)
        self.assertEqual(nothing['features'], [])

    def test_missing_or_bad_bbox(self):
        self.assertEqual(self._buildings(min_lon=1, min_lat=1, max_lon=2).status_code, 400)
        self.assertEqual(self._buildings(min_lon='x', min_lat=1, max_lon=2, max_lat=2).status_code, 400)


class EngreenStationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='engreen-st@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)

    def test_stations_are_proxied(self):
        stations = {'stations': [{'id': 'IT001'}]}
        with patch('requests.get', return_value=http_response(200, stations)) as hal:
            response = self.client.get(reverse('engreen-stations-api'))

        self.assertEqual(response.json(), stations)
        self.assertTrue(hal.call_args.args[0].endswith('/stations'))

    def test_hal_unavailable(self):
        with patch('requests.get', side_effect=requests.ConnectionError()):
            self.assertEqual(self.client.get(reverse('engreen-stations-api')).status_code, 503)


class SaveResultToJupyterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='saver@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)

    def _save(self, body):
        return self.client.post(reverse('dt-save-result'), data=json.dumps(body), content_type='application/json')

    def test_result_is_stored_and_provisioned_into_jupyterhub(self):
        with fake_object_storage() as storage, patch('requests.post', return_value=http_response(200, {})) as dms:
            response = self._save({'twin_slug': 'cea-hydrogen', 'data': {'power': [1, 2]}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['redirect_url'], f"{settings.JUPYTERHUB_URL.rstrip('/')}/user/{self.user.email}/lab",
        )
        saved = DtResult.objects.get(user=self.user)
        self.assertEqual(saved.twin_slug, 'cea-hydrogen')
        self.assertEqual(json.loads(storage.objects[(saved.bucket_name, saved.result_key)]), {'power': [1, 2]})
        self.assertEqual(dms.call_args.kwargs['json']['username'], self.user.email)

    def test_invalid_requests(self):
        for label, body in {
            'unknown twin': {'twin_slug': 'nope', 'data': {}},
            'data not an object': {'twin_slug': 'cea-hydrogen', 'data': [1]},
        }.items():
            with self.subTest(label):
                self.assertEqual(self._save(body).status_code, 400)

    def test_provisioning_failure_is_reported(self):
        with fake_object_storage(), patch('requests.post', side_effect=requests.ConnectionError()):
            response = self._save({'twin_slug': 'cea-hydrogen', 'data': {}})

        self.assertEqual(response.status_code, 502)
        self.assertIn('could not be opened in JupyterHub', response.json()['error'])
