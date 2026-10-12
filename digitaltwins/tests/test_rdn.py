"""RDN Grid DT: simulate, status, follow-up lookup, run pages and the polling task.

Black-box through URLs and task dotted paths, with the RDN API faked at the
`requests` boundary (see test_rdn_results.py for result storage/streaming).
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils.module_loading import import_string
from django_q.models import Schedule

from digitaltwins.models import RdnSimulationJob

from .fakes import queued_task_funcs
from .http_fakes import http_response

User = get_user_model()
Status = RdnSimulationJob.Status

POLL_TASK = 'digitaltwins.rdn.tasks.poll_rdn_job'
RECONCILE_TASK = 'digitaltwins.rdn.tasks.reconcile_stale_rdn_jobs'


def valid_input(**overrides):
    body = {
        'useCase': 'VoltageControl',
        'followsRequestId': None,
        'inputData': {
            'gridSection': 'A',
            'asset': {
                'asset_001': {'assetType': 'PV', 'assetTimeSeries': [
                    {'timestamp_UTC': '2026-01-01T00:00:00Z', 'MW': 10, 'MVAr': 0},
                    {'timestamp_UTC': '2026-01-01T00:15:00Z', 'MW': 12, 'MVAr': 1},
                ]},
                'asset_002': {'assetType': 'Wind', 'assetTimeSeries': [
                    {'timestamp_UTC': '2026-01-01T00:00:00Z', 'MW': 5},
                    {'timestamp_UTC': '2026-01-01T00:15:00Z', 'MW': 6},
                ]},
            },
        },
    }
    body.update(overrides)
    return body


def make_job(user, *, status=Status.RUNNING, **extra):
    job = RdnSimulationJob.objects.create(
        user=user, use_case='VoltageControl', grid_section='A', assets={'asset_001': 'PV'}, status=status, **extra,
    )
    RdnSimulationJob.objects.filter(pk=job.pk).update(rdn_request_id=job.pk)
    job.refresh_from_db()
    return job


class RdnSimulateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='rdn-sim@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.user)
        cache.set('rdn_api_token', 'test-token')  # skip the login round trip

    def _simulate(self, body):
        return self.client.post(reverse('rdn-grid-simulate'), data=json.dumps(body), content_type='application/json')

    def test_valid_input_is_uploaded_and_polled_in_the_background(self):
        with patch('requests.request', return_value=http_response(200, {})) as rdn:
            response = self._simulate(valid_input())

        self.assertEqual(response.status_code, 202)
        job = RdnSimulationJob.objects.get(pk=response.json()['jobId'])
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.status, Status.RUNNING)
        self.assertEqual(job.rdn_request_id, job.pk)
        self.assertEqual(job.assets, {'asset_001': 'PV', 'asset_002': 'Wind'})
        method, url = rdn.call_args.args
        self.assertEqual(method, 'POST')
        self.assertTrue(url.endswith('/inputs/upload'))
        self.assertEqual(rdn.call_args.kwargs['headers'], {'Authorization': 'Bearer test-token'})
        uploaded = json.loads(rdn.call_args.kwargs['files']['file'][1])
        self.assertEqual(uploaded['requestId'], job.pk)
        self.assertEqual(uploaded['inputData']['gridSection'], 'A')
        self.assertEqual(queued_task_funcs(), [POLL_TASK])

    def test_rdn_unreachable_fails_the_job(self):
        with patch('requests.request', side_effect=requests.ConnectionError('down')):
            response = self._simulate(valid_input())

        self.assertEqual(response.status_code, 502)
        job = RdnSimulationJob.objects.get()
        self.assertEqual(job.status, Status.FAILED)
        self.assertIn('Could not reach the RDN API', job.error_message)
        self.assertEqual(queued_task_funcs(), [])

    def test_invalid_inputs_are_rejected_before_anything_is_created(self):
        mismatched = valid_input()
        mismatched['inputData']['asset']['asset_002']['assetTimeSeries'][1]['timestamp_UTC'] = '2026-01-01T00:30:00Z'
        bad_key = valid_input()
        bad_key['inputData']['asset']['pv1'] = bad_key['inputData']['asset'].pop('asset_001')
        cases = {
            'not an object': [1, 2],
            'unknown use case': valid_input(useCase='ShortCircuit'),
            'bad grid section': valid_input(inputData={'gridSection': 'Z', 'asset': {}}),
            'bad asset key': bad_key,
            'assets with different timestamps': mismatched,
            'followsRequestId not an int': valid_input(followsRequestId='7'),
        }
        for label, body in cases.items():
            cache.clear()  # more cases than the simulate rate limit allows per minute
            with self.subTest(label), patch('requests.request') as rdn:
                response = self._simulate(body)
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json())
                rdn.assert_not_called()
        self.assertFalse(RdnSimulationJob.objects.exists())

    def test_malformed_body(self):
        response = self.client.post(reverse('rdn-grid-simulate'), data='{', content_type='application/json')
        self.assertEqual(response.status_code, 400)


class RdnStatusAndLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email='rdn-owner2@example.com', password='pw')
        cls.other = User.objects.create_user(email='rdn-other2@example.com', password='pw')

    def setUp(self):
        self.client.force_login(self.owner)

    def test_status_of_a_running_job(self):
        job = make_job(self.owner)
        response = self.client.get(reverse('rdn-grid-job-status'), {'job': job.pk})
        self.assertEqual(response.json(), {'status': 'running', 'requestId': job.pk})

    def test_status_of_a_failed_job_carries_the_error(self):
        job = make_job(self.owner, status=Status.FAILED, error_message='RDN said no')
        response = self.client.get(reverse('rdn-grid-job-status'), {'job': job.pk})
        self.assertEqual(response.json()['error'], 'RDN said no')

    def test_status_of_another_users_job_is_404(self):
        job = make_job(self.other)
        response = self.client.get(reverse('rdn-grid-job-status'), {'job': job.pk})
        self.assertEqual(response.status_code, 404)

    def test_status_with_a_bad_id(self):
        self.assertEqual(self.client.get(reverse('rdn-grid-job-status'), {'job': 'x'}).status_code, 400)

    def test_follow_lookup_finds_own_completed_runs_only(self):
        own = make_job(self.owner, status=Status.COMPLETED)
        running = make_job(self.owner)
        foreign = make_job(self.other, status=Status.COMPLETED)
        url = reverse('rdn-grid-follow')

        self.assertEqual(self.client.get(url, {'requestId': own.pk}).json(), {
            'found': True, 'gridSection': 'A', 'useCase': 'VoltageControl', 'assets': {'asset_001': 'PV'},
        })
        self.assertEqual(self.client.get(url, {'requestId': running.pk}).json(), {'found': False})
        self.assertEqual(self.client.get(url, {'requestId': foreign.pk}).json(), {'found': False})
        self.assertEqual(self.client.get(url, {'requestId': 'x'}).status_code, 400)

    def test_runs_page_lists_own_jobs_only(self):
        own = make_job(self.owner, status=Status.COMPLETED)
        make_job(self.other)

        response = self.client.get(reverse('rdn-grid-runs'))

        self.assertEqual([job.pk for job in response.context['page_obj']], [own.pk])
        self.assertEqual(response.context['page_obj'][0].use_case_label, 'Voltage control')

    def test_results_page(self):
        own = make_job(self.owner, status=Status.COMPLETED, result={'outputData': []})
        foreign = make_job(self.other, status=Status.COMPLETED)

        response = self.client.get(reverse('rdn-grid-results', args=[own.rdn_request_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['assets_breakdown'], '1 PV')
        self.assertEqual(response.context['result_url'], reverse('rdn-grid-result-data', args=[own.rdn_request_id]))

        self.assertEqual(self.client.get(reverse('rdn-grid-results', args=[foreign.rdn_request_id])).status_code, 404)


class RdnPollingTaskTests(TestCase):
    """The poll chain lives in django_q Schedule rows, which store the task's dotted path."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email='rdn-poll@example.com', password='pw')

    def setUp(self):
        cache.set('rdn_api_token', 'test-token')

    def test_still_running_schedules_the_next_check(self):
        job = make_job(self.user)

        with patch('requests.request', return_value=http_response(200, {'status': 'running'})):
            import_string(POLL_TASK)(job.pk)

        schedule = Schedule.objects.get(func=POLL_TASK)  # (migration 0004 adds the hourly reconcile row)
        self.assertEqual(schedule.args, f'({job.pk},)')
        job.refresh_from_db()
        self.assertEqual(job.status, Status.RUNNING)

    def test_unreachable_rdn_retries_later(self):
        job = make_job(self.user)

        with patch('requests.request', side_effect=requests.ConnectionError('down')):
            import_string(POLL_TASK)(job.pk)

        self.assertTrue(Schedule.objects.filter(func=POLL_TASK).exists())

    def test_failed_on_rdns_side(self):
        job = make_job(self.user)

        with patch('requests.request', return_value=http_response(200, {'status': 'failed', 'errorMessage': 'diverged'})):
            import_string(POLL_TASK)(job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, Status.FAILED)
        self.assertEqual(job.error_message, 'diverged')
        self.assertFalse(Schedule.objects.filter(func=POLL_TASK).exists())

    def test_finished_jobs_are_left_alone(self):
        job = make_job(self.user, status=Status.COMPLETED)

        with patch('requests.request') as rdn:
            import_string(POLL_TASK)(job.pk)

        rdn.assert_not_called()

    def test_reconcile_fails_jobs_stuck_for_a_week(self):
        stale = make_job(self.user)
        fresh = make_job(self.user)
        RdnSimulationJob.objects.filter(pk=stale.pk).update(created_at=datetime.now(timezone.utc) - timedelta(days=8))

        self.assertEqual(import_string(RECONCILE_TASK)(), 1)

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(stale.status, Status.FAILED)
        self.assertEqual(fresh.status, Status.RUNNING)
