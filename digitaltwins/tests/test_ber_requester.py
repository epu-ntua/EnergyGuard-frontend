"""BER experiment requests, from the requester's side.

Black-box tests through the URLs: they pin the behaviour that the code
reorganisation of the digitaltwins app must preserve.
"""

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from digitaltwins.ber.tasks import warm_ber_results_cache
from digitaltwins.models import BerExperimentRequest

from .ber_factories import VALID_EXPERIMENT, make_completed_request, make_request, make_user
from .fakes import SAMPLE_LP, fake_object_storage, queued_task_funcs

Status = BerExperimentRequest.Status


def build(experiment_request):
    """Run the qcluster build of the results page, as the worker would."""
    warm_ber_results_cache(experiment_request.pk)


class BerSubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('ber-submitter@example.com')

    def setUp(self):
        self.client.force_login(self.user)

    def _submit(self, payload):
        return self.client.post(
            reverse('ber-hydrogen-submit'), data=json.dumps(payload), content_type='application/json',
        )

    @override_settings(BER_EMAIL='ber-lab@example.com')
    def test_valid_submission_creates_a_pending_request_and_notifies_ber(self):
        response = self._submit(VALID_EXPERIMENT)

        self.assertEqual(response.status_code, 202)
        experiment_request = BerExperimentRequest.objects.get(pk=response.json()['requestId'])
        self.assertEqual(experiment_request.user, self.user)
        self.assertEqual(experiment_request.status, Status.PENDING)
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.notify_ber_staff_of_new_request'])

    @override_settings(BER_EMAIL='')
    def test_staff_are_still_notified_without_a_ber_address(self):
        # The task sends the in-app notifications; only its email is skipped.
        self.assertEqual(self._submit(VALID_EXPERIMENT).status_code, 202)
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.notify_ber_staff_of_new_request'])

    def test_invalid_experiment_is_rejected(self):
        response = self._submit([{'time': 0, 'command': 'explode', 'value': 'now'}])

        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertFalse(BerExperimentRequest.objects.exists())

    def test_nan_time_is_rejected_not_a_server_error(self):
        body = '[{"time": NaN, "command": "set_control_mode", "value": "amp"},' \
               ' {"time": 1, "command": "set_regen_mode", "value": "instant"}]'
        response = self.client.post(reverse('ber-hydrogen-submit'), data=body, content_type='application/json')

        self.assertEqual(response.status_code, 400)

    def test_malformed_body_is_rejected(self):
        response = self.client.post(reverse('ber-hydrogen-submit'), data='{', content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_identical_retry_returns_the_original_request(self):
        first = self._submit(VALID_EXPERIMENT).json()['requestId']
        second = self._submit(VALID_EXPERIMENT).json()['requestId']

        self.assertEqual(first, second)
        self.assertEqual(BerExperimentRequest.objects.count(), 1)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(reverse('ber-hydrogen-submit')).status_code, 405)


class BerRequesterAccessTests(TestCase):
    """A requester only ever reaches their own requests."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('ber-owner@example.com')
        cls.other = make_user('ber-other@example.com')

    def test_another_users_request_is_404_everywhere(self):
        experiment_request = make_request(self.owner, status=Status.COMPLETED, result_key='x/y.lp')
        self.client.force_login(self.other)

        for name, method in [
            ('ber-hydrogen-request-detail', 'get'),
            ('ber-hydrogen-request-status', 'get'),
            ('ber-hydrogen-request-result-download', 'get'),
            ('ber-hydrogen-request-cancel', 'post'),
            ('ber-hydrogen-request-hide', 'post'),
        ]:
            with self.subTest(name=name):
                response = getattr(self.client, method)(reverse(name, args=[experiment_request.pk]))
                self.assertEqual(response.status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        experiment_request = make_request(self.owner)
        response = self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))
        self.assertEqual(response.status_code, 302)

    def test_list_shows_only_own_visible_requests(self):
        own = make_request(self.owner)
        hidden = make_request(self.owner, status=Status.REJECTED)
        BerExperimentRequest.objects.filter(pk=hidden.pk).update(hidden_by_user_at=own.created_at)
        foreign = make_request(self.other)

        self.client.force_login(self.owner)
        listed = [r.pk for r in self.client.get(reverse('ber-hydrogen-runs')).context['page_obj']]

        self.assertEqual(listed, [own.pk])
        self.assertNotIn(foreign.pk, listed)

    def test_status_endpoint_reports_the_status(self):
        experiment_request = make_request(self.owner)
        self.client.force_login(self.owner)

        response = self.client.get(reverse('ber-hydrogen-request-status', args=[experiment_request.pk]))

        self.assertEqual(response.json(), {'status': 'pending'})


class BerCancelAndHideTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('ber-cancel@example.com')

    def setUp(self):
        self.client.force_login(self.owner)

    @override_settings(BER_EMAIL='ber-lab@example.com')
    def test_cancelling_a_pending_request_notifies_ber(self):
        experiment_request = make_request(self.owner)

        response = self.client.post(reverse('ber-hydrogen-request-cancel', args=[experiment_request.pk]))

        self.assertRedirects(
            response, reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]),
            fetch_redirect_response=False,
        )
        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.CANCELLED)
        self.assertIsNotNone(experiment_request.cancelled_at)
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.notify_ber_staff_of_cancellation'])

    @override_settings(BER_EMAIL='ber-lab@example.com')
    def test_a_decided_request_cannot_be_cancelled(self):
        experiment_request = make_request(self.owner, status=Status.COMPLETED)

        self.client.post(reverse('ber-hydrogen-request-cancel', args=[experiment_request.pk]))

        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.COMPLETED)
        self.assertEqual(queued_task_funcs(), [])

    def test_cancel_requires_post(self):
        experiment_request = make_request(self.owner)
        response = self.client.get(reverse('ber-hydrogen-request-cancel', args=[experiment_request.pk]))
        self.assertEqual(response.status_code, 405)

    def test_hiding_a_finished_request(self):
        experiment_request = make_request(self.owner, status=Status.REJECTED)

        response = self.client.post(reverse('ber-hydrogen-request-hide', args=[experiment_request.pk]))

        self.assertRedirects(response, reverse('ber-hydrogen-runs'), fetch_redirect_response=False)
        experiment_request.refresh_from_db()
        self.assertIsNotNone(experiment_request.hidden_by_user_at)

    def test_a_pending_request_cannot_be_hidden(self):
        experiment_request = make_request(self.owner)

        self.client.post(reverse('ber-hydrogen-request-hide', args=[experiment_request.pk]))

        experiment_request.refresh_from_db()
        self.assertIsNone(experiment_request.hidden_by_user_at)


class BerResultsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('ber-results@example.com')

    def setUp(self):
        self.client.force_login(self.owner)

    def test_pending_request_shows_the_waiting_page(self):
        experiment_request = make_request(self.owner)

        response = self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))

        self.assertTemplateUsed(response, 'digitaltwins/ber/request-detail.html')
        self.assertContains(response, 'Waiting for the BER laboratory')

    def _view(self, experiment_request):
        return self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))

    def test_first_view_queues_one_build_and_shows_it_is_being_prepared(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            first = self._view(experiment_request)
            second = self._view(experiment_request)

        for response in (first, second):
            self.assertTemplateUsed(response, 'digitaltwins/ber/request-detail.html')
            self.assertContains(response, 'results are being prepared')
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.warm_ber_results_cache'])

    def test_the_view_never_reads_the_result_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            with patch('digitaltwins.ber.services.results.open_result_file') as open_file:
                self._view(experiment_request)

        open_file.assert_not_called()

    def test_completed_request_renders_kpis_parsed_from_the_result_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            build(experiment_request)
            response = self._view(experiment_request)

        self.assertTemplateUsed(response, 'digitaltwins/ber/results.html')
        kpis = response.context['kpis']
        self.assertEqual(kpis['peak_total_power'], 6.5)
        self.assertEqual(kpis['avg_stack_power'], 4.0)
        self.assertEqual(kpis['avg_aux_power'], 1.25)
        self.assertEqual(kpis['peak_stack_current'], 120.0)
        self.assertEqual(kpis['peak_stack_voltage'], 42.0)
        self.assertEqual(response.context['serial_number'], '6')
        self.assertEqual(response.context['duration_label'], '0m 01s')
        self.assertEqual(response.context['chart_power_axis'], {'min': 0, 'max': 8})
        self.assertEqual(
            response.context['experiment_id'],
            f'BER-{experiment_request.created_at:%Y}-{experiment_request.pk:06d}',
        )

    def test_parsed_results_are_cached(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            build(experiment_request)
            storage.fail_reads = True
            response = self._view(experiment_request)

        self.assertTemplateUsed(response, 'digitaltwins/ber/results.html')

    def test_result_file_without_power_signals_shows_a_message(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=b'not,a power file\n')
            build(experiment_request)
            response = self._view(experiment_request)

        self.assertContains(response, 'could not be read')
        self.assertEqual(queued_task_funcs(), [], 'a file known to be unreadable must not be rebuilt')

    def test_unreachable_storage_shows_a_retry_message(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            storage.fail_reads = True
            build(experiment_request)
            response = self._view(experiment_request)

        self.assertContains(response, 'could not be loaded right now')

    def test_an_unexpected_build_error_is_reported_and_not_retried_on_every_view(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            with patch('digitaltwins.ber.services.results._compute_ber_kpis', side_effect=ValueError('bug')):
                build(experiment_request)
            first = self._view(experiment_request)
            second = self._view(experiment_request)

        for response in (first, second):
            self.assertContains(response, 'Something went wrong while preparing the results')
        self.assertEqual(queued_task_funcs(), [], 'a bug must not trigger a re-parse on every view')

    def test_a_build_is_queued_again_once_the_storage_failure_is_forgotten(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            storage.fail_reads = True
            build(experiment_request)
            cache.clear()  # the short-lived failure marker has expired
            response = self._view(experiment_request)

        self.assertContains(response, 'results are being prepared')
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.warm_ber_results_cache'])

    def test_completed_without_a_file_says_so(self):
        experiment_request = make_request(self.owner, status=Status.COMPLETED)
        response = self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))
        self.assertContains(response, 'result file is not available yet')

    def test_owner_downloads_the_result_file_under_the_experiment_id(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            response = self.client.get(
                reverse('ber-hydrogen-request-result-download', args=[experiment_request.pk]),
            )
            content = b''.join(response.streaming_content)

        self.assertEqual(content, SAMPLE_LP)
        self.assertEqual(
            response['Content-Disposition'],
            f'attachment; filename="BER-{experiment_request.created_at:%Y}-{experiment_request.pk:06d}.lp"',
        )

    def test_pending_request_has_no_download(self):
        experiment_request = make_request(self.owner)
        response = self.client.get(reverse('ber-hydrogen-request-result-download', args=[experiment_request.pk]))
        self.assertEqual(response.status_code, 404)
