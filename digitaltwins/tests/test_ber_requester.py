"""BER experiment requests, from the requester's side.

Black-box tests through the URLs: they pin the behaviour that the code
reorganisation of the digitaltwins app must preserve.
"""

import json

from django.test import TestCase, override_settings
from django.urls import reverse

from digitaltwins.models import BerExperimentRequest

from .ber_factories import VALID_EXPERIMENT, make_completed_request, make_request, make_user
from .fakes import SAMPLE_LP, fake_object_storage, queued_task_funcs

Status = BerExperimentRequest.Status


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
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.send_ber_notification_email'])

    @override_settings(BER_EMAIL='')
    def test_no_notification_without_a_ber_address(self):
        self.assertEqual(self._submit(VALID_EXPERIMENT).status_code, 202)
        self.assertEqual(queued_task_funcs(), [])

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
        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.send_ber_cancellation_email'])

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

        self.assertTemplateUsed(response, 'digitaltwins/ber-hydrogen-request-detail.html')
        self.assertContains(response, 'Waiting for the BER laboratory')

    def test_completed_request_renders_kpis_parsed_from_the_result_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            response = self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))

        self.assertTemplateUsed(response, 'digitaltwins/ber-hydrogen-results.html')
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
            url = reverse('ber-hydrogen-request-detail', args=[experiment_request.pk])
            self.client.get(url)
            storage.fail_reads = True
            response = self.client.get(url)

        self.assertTemplateUsed(response, 'digitaltwins/ber-hydrogen-results.html')

    def test_result_file_without_power_signals_shows_a_message(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=b'not,a power file\n')
            response = self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))

        self.assertContains(response, 'could not be read')

    def test_unreachable_storage_shows_a_retry_message(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.owner, storage, data=SAMPLE_LP)
            storage.fail_reads = True
            response = self.client.get(reverse('ber-hydrogen-request-detail', args=[experiment_request.pk]))

        self.assertContains(response, 'could not be loaded right now')

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
