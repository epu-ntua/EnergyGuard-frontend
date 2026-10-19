"""Riga buildings API, Engreen stations, and saving a twin's result to JupyterHub."""

import json
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.contrib.messages import get_messages
from django.urls import reverse

from datasets.models import Dataset
from digitaltwins.catalog import DIGITAL_TWINS
from digitaltwins.models import DtExport, DtRun, RdnSimulationJob
from digitaltwins.runs.services import record_run

from .ber_factories import make_completed_request
from .fakes import SAMPLE_LP, fake_object_storage, queued_task_funcs
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


def make_rdn_job(user, *, rdn_request_id, **extra):
    job = RdnSimulationJob.objects.create(
        user=user, use_case='VoltageControl', grid_section='A',
        status=RdnSimulationJob.Status.COMPLETED, **extra,
    )
    RdnSimulationJob.objects.filter(pk=job.pk).update(rdn_request_id=rdn_request_id)
    return job


# Names are asserted as production makes them, whatever the machine's .env says.
@override_settings(DT_EXPORT_NAME_PREFIX='')
class SaveResultToJupyterTests(TestCase):
    """The browser names a stored result; the server copies it for JupyterHub."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='saver@example.com', password='pw')
        cls.other = User.objects.create_user(email='other-saver@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)
        self.storage = self.enterContext(fake_object_storage())
        self.dms = self.enterContext(patch('requests.post', return_value=http_response(200, {})))

    def _save(self, body):
        return self.client.post(reverse('dt-save-result'), data=json.dumps(body), content_type='application/json')

    def _exported_bytes(self, export):
        return self.storage.objects[(settings.OBJECT_STORAGE_BUCKET, export.result_key)]

    def test_run_result_is_copied_uncompressed_and_provisioned(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical',
                         inputs={}, result={'summary': {'pnom_kw': 4}})

        response = self._save({'source': 'run', 'id': run.pk})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['redirect_url'], f"{settings.JUPYTERHUB_URL.rstrip('/')}/user/{self.user.email}/lab",
        )
        exported = DtExport.objects.get(user=self.user)
        self.assertEqual(exported.twin_slug, 'engreen-antrodoco')
        self.assertEqual(exported.source_key, run.result_key)
        # Named after the run as the user sees it, in the user's folder, like the datasets.
        self.assertEqual(exported.result_key,
                         f'user_saverexamplecom/engreen-antrodoco-historical-run-{run.pk}/result.json')
        self.assertEqual(json.loads(self._exported_bytes(exported)), {'summary': {'pnom_kw': 4}})
        provisioned = self.dms.call_args.kwargs['json']
        self.assertEqual(provisioned['username'], self.user.email)
        self.assertEqual(provisioned['datasets'], {
            f'user_saverexamplecom/engreen-antrodoco-historical-run-{run.pk}':
                f'engreen-antrodoco-historical-run-{run.pk}',
        })

    @override_settings(DT_EXPORT_NAME_PREFIX='dev-')
    def test_a_development_machine_prefixes_its_copies(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        self._save({'source': 'run', 'id': run.pk})
        self.assertEqual(DtExport.objects.get(user=self.user).result_key,
                         f'user_saverexamplecom/dev-engreen-antrodoco-historical-run-{run.pk}/result.json')

    def test_opening_the_same_result_again_reuses_the_copy(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        self._save({'source': 'run', 'id': run.pk})
        self._save({'source': 'run', 'id': run.pk})
        self.assertEqual(DtExport.objects.filter(user=self.user).count(), 1)

    def test_a_replaced_ber_result_is_exported_again_into_the_same_copy(self):
        experiment_request = make_completed_request(self.user, self.storage, data=SAMPLE_LP)
        self._save({'source': 'ber', 'id': experiment_request.pk})

        new_key = f'ber-hydrogen/{experiment_request.pk}/result-replaced.lp'
        replaced = SAMPLE_LP + b'power,serialNumber=6 JT_3001=7.0 1700000002000000000\n'
        self.storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, new_key)] = replaced
        experiment_request.__class__.objects.filter(pk=experiment_request.pk).update(result_key=new_key)
        self._save({'source': 'ber', 'id': experiment_request.pk})

        exported = DtExport.objects.get(user=self.user)
        self.assertEqual(exported.source_key, new_key)
        self.assertEqual(self._exported_bytes(exported), replaced)

    def test_ber_result_file_is_copied_as_is(self):
        experiment_request = make_completed_request(self.user, self.storage, data=SAMPLE_LP)

        self.assertEqual(self._save({'source': 'ber', 'id': experiment_request.pk}).status_code, 200)

        exported = DtExport.objects.get(user=self.user)
        self.assertEqual(
            exported.result_key,
            f'user_saverexamplecom/ber-hydrogen-request-{experiment_request.pk}/'
            f'BER-{experiment_request.created_at:%Y}-{experiment_request.pk:06d}.lp',
        )
        self.assertEqual(self._exported_bytes(exported), SAMPLE_LP)

    def test_rdn_result_is_copied_and_legacy_inline_results_still_export(self):
        stored = make_rdn_job(self.user, rdn_request_id=501, result_key='rdn-grid/501/result.json')
        self.storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, stored.result_key)] = b'{"a": 1}'
        make_rdn_job(self.user, rdn_request_id=502, result={'b': 2})

        self.assertEqual(self._save({'source': 'rdn', 'id': 501}).status_code, 200)
        self.assertEqual(self._save({'source': 'rdn', 'id': 502}).status_code, 200)

        exported = {r.source_key: json.loads(self._exported_bytes(r)) for r in DtExport.objects.filter(user=self.user)}
        self.assertEqual(exported, {'rdn-grid/501/result.json': {'a': 1}, 'rdn-grid/502/result.json': {'b': 2}})

    def test_another_users_result_cannot_be_exported(self):
        run = record_run(user=self.other, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        theirs = make_completed_request(self.other, self.storage, data=SAMPLE_LP)

        self.assertEqual(self._save({'source': 'run', 'id': run.pk}).status_code, 404)
        self.assertEqual(self._save({'source': 'ber', 'id': theirs.pk}).status_code, 404)
        self.assertFalse(DtExport.objects.exists())

    def test_invalid_requests(self):
        for label, body in {
            'browser-sent data': {'twin_slug': 'cea-hydrogen', 'data': {'power': [1]}},
            'unknown source': {'source': 'nope', 'id': 1},
            'id not an integer': {'source': 'run', 'id': '1'},
        }.items():
            with self.subTest(label):
                self.assertEqual(self._save(body).status_code, 400)

    def test_exports_are_rate_limited(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        statuses = [self._save({'source': 'run', 'id': run.pk}).status_code for _ in range(11)]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10], 429)

    def test_provisioning_failure_is_reported(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        self.dms.side_effect = requests.ConnectionError()

        response = self._save({'source': 'run', 'id': run.pk})

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


class RemovingAResultRemovesItsJupyterHubCopiesTests(TestCase):
    """Deleting a run (or removing a BER request) also removes what was exported
    from it: the datasets-bucket copy, the file in JupyterHub, the DtExport row."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='cleaner@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)
        self.storage = self.enterContext(fake_object_storage())
        self.enterContext(patch('requests.post', return_value=http_response(200, {})))
        self.jupyterhub_delete = self.enterContext(patch('requests.delete', return_value=http_response(200, {})))
        # The JupyterHub clean-up is a qcluster task; run it in place here.
        self.enterContext(patch('django_q.conf.Conf.SYNC', True))

    def _export(self, source, source_id):
        response = self.client.post(reverse('dt-save-result'), data=json.dumps({'source': source, 'id': source_id}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return DtExport.objects.latest('pk')

    def _assert_export_gone(self, export):
        self.assertFalse(DtExport.objects.filter(pk=export.pk).exists())
        self.assertNotIn((export.bucket_name, export.result_key), self.storage.objects)
        local_name = export.result_key.rsplit('/', 2)[1]
        # The data-management server is asked to drop the file, by the user's email (URL-encoded).
        self.assertTrue(self.jupyterhub_delete.call_args.args[0].endswith(f"/{quote(self.user.email, safe='')}/{local_name}"))

    def test_deleting_a_dt_run(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        export = self._export('run', run.pk)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dt-run-delete', args=[run.pk]))

        self._assert_export_gone(export)
        self.assertEqual(self.storage.objects, {})

    def test_deleting_an_rdn_run(self):
        key = 'rdn-grid/801/result.json'
        self.storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, key)] = b'{}'
        make_rdn_job(self.user, rdn_request_id=801, result_key=key)
        export = self._export('rdn', 801)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('rdn-grid-run-delete', args=[801]))

        self._assert_export_gone(export)
        self.assertEqual(self.storage.objects, {})

    def test_removing_a_ber_request_keeps_the_file_ber_staff_see(self):
        experiment_request = make_completed_request(self.user, self.storage, data=SAMPLE_LP)
        export = self._export('ber', experiment_request.pk)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('ber-hydrogen-request-hide', args=[experiment_request.pk]))

        self._assert_export_gone(export)
        self.assertIn(
            (settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, export.source_key),
            self.storage.objects,
        )

    def test_jupyterhub_being_down_does_not_stop_the_delete(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        export = self._export('run', run.pk)
        self.jupyterhub_delete.side_effect = requests.ConnectionError()

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dt-run-delete', args=[run.pk]))

        self.assertFalse(DtRun.objects.filter(pk=run.pk).exists())
        self.assertFalse(DtExport.objects.filter(pk=export.pk).exists())

    def test_deleting_the_account_removes_its_jupyterhub_copies(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        export = self._export('run', run.pk)

        with self.captureOnCommitCallbacks(execute=True):
            self.user.delete()

        self.assertEqual(self.storage.objects, {})
        self.assertTrue(self.jupyterhub_delete.called)
        self.assertFalse(DtExport.objects.filter(pk=export.pk).exists())

    def test_the_jupyterhub_clean_up_is_queued_not_run_in_the_request(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        self._export('run', run.pk)

        with patch('django_q.conf.Conf.SYNC', False), self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dt-run-delete', args=[run.pk]))

        self.jupyterhub_delete.assert_not_called()
        self.assertIn('digitaltwins.services.jupyterhub_export.discard_export', queued_task_funcs())

    def test_other_runs_exports_are_left_alone(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        other = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={}, result={})
        kept = self._export('run', other.pk)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dt-run-delete', args=[run.pk]))

        self.assertTrue(DtExport.objects.filter(pk=kept.pk).exists())
