"""Riga buildings API, Engreen stations, and saving a twin's result to JupyterHub."""

import json
from decimal import Decimal
from unittest.mock import patch

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.contrib.messages import get_messages
from django.urls import reverse

from datasets.models import Dataset
from digitaltwins.catalog import DIGITAL_TWINS
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


class PilotDatasetLinkTests(TestCase):
    """Overview pages link to the twin's pilot dataset by partner, not by an id
    that differs between environments."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='pilot-links@example.com', password='pw')
        # Unrelated datasets first, so the pilot one's id is not something a test could guess.
        for i in range(3):
            Dataset.objects.create(name=f'Other {i}', size_gb=Decimal('0.01'))
        cls.ber_dataset = Dataset.objects.create(
            name='BER Pilot Data', size_gb=Decimal('0.01'), metadata={'pilot_partner': 'BER'},
            status=Dataset.Status.APPROVED, visibility=True,
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_redirects_to_the_partners_dataset(self):
        response = self.client.get(reverse('digitaltwins-pilot-dataset', args=['ber-hydrogen']))
        self.assertRedirects(
            response, reverse('dataset_details', kwargs={'dataset_id': self.ber_dataset.pk}),
            fetch_redirect_response=False,
        )

    def test_found_by_its_export_when_the_metadata_lost_the_partner(self):
        """As on the server: renamed, and metadata replaced by the signal dictionary."""
        ceder = Dataset.objects.create(
            name='CEDER-CIEMAT Microgrid — Real-Time DER Operation and Meteorological Dataset',
            size_gb=Decimal('0.01'), data_file='pilot_datasets/CEDER/CEDER.csv.gz',
            metadata={'ED09': ['W', 'PV Production']},
        )

        response = self.client.get(reverse('digitaltwins-pilot-dataset', args=['ciemat-microgrid']))

        self.assertRedirects(
            response, reverse('dataset_details', kwargs={'dataset_id': ceder.pk}), fetch_redirect_response=False,
        )

    def test_dataset_not_seeded_yet(self):
        response = self.client.get(reverse('digitaltwins-pilot-dataset', args=['cea-hydrogen']))

        self.assertRedirects(response, reverse('datasets_list'), fetch_redirect_response=False)
        self.assertIn("isn't available yet", str(list(get_messages(response.wsgi_request))[0]))

    def test_twins_without_a_pilot_dataset(self):
        for slug in ['rdn-grid', 'no-such-twin']:
            with self.subTest(slug):
                self.assertEqual(self.client.get(reverse('digitaltwins-pilot-dataset', args=[slug])).status_code, 404)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('digitaltwins-pilot-dataset', args=['ber-hydrogen']))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('/datasets/dataset/', response['Location'], 'sent to login, not to the dataset')

    def test_every_overview_links_by_partner(self):
        for twin in DIGITAL_TWINS:
            if not twin.get('pilot_partner'):
                continue
            with self.subTest(twin['slug']):
                response = self.client.get(reverse('digitaltwins-detail', args=[twin['slug']]))
                self.assertContains(response, reverse('digitaltwins-pilot-dataset', args=[twin['slug']]))
                self.assertNotContains(response, '/datasets/dataset/')
