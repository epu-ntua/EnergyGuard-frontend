"""Run history of the twins that answer straight away: recording, the list and
reopening a run."""

import gzip
import io
import json
from unittest.mock import patch

from botocore.exceptions import ClientError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.urls import reverse

from digitaltwins.models import DtRun
from digitaltwins.runs.services import MAX_RESULT_BYTES, record_run

from .fakes import fake_object_storage
from .http_fakes import http_response

User = get_user_model()


class RunsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='runner@example.com', password='pw')
        cls.other = User.objects.create_user(email='other-runner@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)
        self.storage = self.enterContext(fake_object_storage())

    def stored_result(self, run):
        return json.loads(gzip.decompress(self.storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, run.result_key)]))

    def make_run(self, user=None, **extra):
        return record_run(user=user or self.user, twin_slug='engreen-antrodoco', operation='historical',
                          inputs={'mode': 'existing', 'station': 'IT001'}, result={'summary': {}}, **extra)


class RecordingTests(RunsTestCase):
    def test_engreen_run_is_recorded_with_its_inputs_and_result(self):
        hal_answer = {'summary': {'pnom_kw': 4}, 'monthly': []}
        with patch('requests.post', return_value=http_response(200, hal_answer)):
            response = self.client.post(reverse('engreen-pv-simulate'), data=json.dumps({
                'mode': 'existing', 'forecast_type': 'short-term', 'station': 'IT001', 'days': 7,
            }), content_type='application/json')

        run = DtRun.objects.get(user=self.user)
        self.assertEqual(response['X-DT-Run-Id'], str(run.pk))
        self.assertNotIn('run_id', response.json())
        self.assertEqual((run.twin_slug, run.operation, run.status),
                         ('engreen-antrodoco', 'short-term', DtRun.Status.COMPLETED))
        self.assertEqual(run.inputs, {'mode': 'existing', 'station': 'IT001', 'days': 7})
        self.assertEqual(self.stored_result(run), hal_answer)
        self.assertRegex(run.result_key,
                         r'^dt-runs/engreen-antrodoco/user_runnerexamplecom/\d{8}-\d{6}-[0-9a-f]{8}/result\.json\.gz$')

    @override_settings(CIEMAT_API_KEY='test-key')
    def test_a_failed_service_call_is_recorded_without_a_result(self):
        with patch('requests.post', return_value=http_response(500, {})):
            response = self.client.post(reverse('ciemat-forecast'), data=json.dumps({
                'generation_type': 'wind', 'lat': 41.5, 'lon': -2.5,
            }), content_type='application/json')

        self.assertEqual(response.status_code, 502)
        run = DtRun.objects.get(user=self.user)
        self.assertEqual((run.operation, run.status, run.result_key), ('forecast', DtRun.Status.FAILED, ''))
        self.assertTrue(run.error_message)

    def test_a_result_over_the_size_limit_is_not_kept(self):
        run = record_run(user=self.user, twin_slug='engreen-antrodoco', operation='historical', inputs={},
                         result={'blob': 'x' * MAX_RESULT_BYTES})
        self.assertEqual((run.status, run.result_key), (DtRun.Status.NOT_KEPT, ''))
        self.assertEqual(self.storage.objects, {})

    def test_a_failed_row_write_does_not_orphan_the_uploaded_result(self):
        with patch.object(DtRun.objects, 'create', side_effect=RuntimeError('db down')):
            run = self.make_run()
        self.assertIsNone(run)
        self.assertEqual(self.storage.objects, {})

    def test_deleting_the_account_removes_its_stored_results(self):
        """The CASCADE from an account deletion must not leave personal data behind."""
        user = User.objects.create_user(email='leaving@example.com', password='pw')
        self.make_run(user=user)
        with self.captureOnCommitCallbacks(execute=True):
            user.delete()
        self.assertEqual(self.storage.objects, {})

    def test_a_storage_failure_does_not_fail_the_run(self):
        error = ClientError({'Error': {'Code': 'InternalError', 'Message': 'boom'}}, 'PutObject')
        with patch.object(self.storage, 'put_object', side_effect=error):
            run = self.make_run()
        self.assertEqual(run.status, DtRun.Status.NOT_KEPT)


class RunPagesTests(RunsTestCase):
    def test_list_shows_only_the_users_runs_of_that_twin(self):
        mine = self.make_run()
        theirs = self.make_run(user=self.other)
        record_run(user=self.user, twin_slug='ciemat-microgrid', operation='forecast', inputs={}, result={})

        response = self.client.get(reverse('dt-runs', args=['engreen-antrodoco']))

        self.assertEqual([run.pk for run in response.context['page_obj']], [mine.pk])
        self.assertNotContains(response, f'#{theirs.pk}<')

    def test_list_actions_name_the_run(self):
        run = self.make_run()
        response = self.client.get(reverse('dt-runs', args=['engreen-antrodoco']))
        self.assertContains(response, f'data-confirm-title="Delete run #{run.pk}"')
        self.assertContains(response, reverse('dt-run-delete', args=[run.pk]))
        self.assertNotContains(response, '{{')

    def test_twins_without_run_history_have_no_list(self):
        self.assertEqual(self.client.get(reverse('dt-runs', args=['rdn-grid'])).status_code, 404)

    def test_result_is_served_gzipped_for_the_browser_to_decompress(self):
        run = self.make_run()
        response = self.client.get(reverse('dt-run-result-data', args=[run.pk]), HTTP_ACCEPT_ENCODING='gzip, deflate, br')
        self.assertEqual(response['Content-Encoding'], 'gzip')
        self.assertIn('Accept-Encoding', response['Vary'])
        self.assertEqual(json.loads(gzip.decompress(b''.join(response.streaming_content))), {'summary': {}})

    def test_a_client_without_gzip_gets_plain_json(self):
        run = self.make_run()
        response = self.client.get(reverse('dt-run-result-data', args=[run.pk]))
        self.assertFalse(response.has_header('Content-Encoding'))
        self.assertEqual(json.loads(b''.join(response.streaming_content)), {'summary': {}})

    def test_reopening_a_run_renders_the_workspace_with_it(self):
        run = self.make_run()
        response = self.client.get(reverse('engreen-antrodoco-run', args=[run.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('dt-run-result-data', args=[run.pk]))

    def test_another_users_run_is_out_of_reach(self):
        theirs = self.make_run(user=self.other)
        for response in (
            self.client.get(reverse('dt-run-result-data', args=[theirs.pk])),
            self.client.get(reverse('engreen-antrodoco-run', args=[theirs.pk])),
            self.client.post(reverse('dt-run-delete', args=[theirs.pk])),
        ):
            self.assertEqual(response.status_code, 404)
        self.assertTrue(DtRun.objects.filter(pk=theirs.pk).exists())

    def test_delete_removes_the_run_and_its_result(self):
        run = self.make_run()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dt-run-delete', args=[run.pk]))
        self.assertFalse(DtRun.objects.filter(pk=run.pk).exists())
        self.assertEqual(self.storage.objects, {})


class StorageUsageCommandTests(RunsTestCase):
    def test_reports_usage_per_twin_and_the_orphans(self):
        self.make_run()
        orphan = 'dt-runs/engreen-antrodoco/user_x/20260101-000000-deadbeef/result.json.gz'
        self.storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, orphan)] = b'x' * 10

        out = io.StringIO()
        call_command('dt_storage_usage', '--orphans', stdout=out)

        self.assertIn('engreen-antrodoco', out.getvalue())
        self.assertIn('Orphaned results in', out.getvalue())
        self.assertIn(orphan, out.getvalue())

