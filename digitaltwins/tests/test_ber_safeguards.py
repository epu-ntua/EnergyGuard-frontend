"""Safeguards around BER requests: submission limits, duplicate submissions,
plausible execution times, result files of deleted requests, and email links."""

import json
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.module_loading import import_string

from digitaltwins.ber.services.requests import MAX_PENDING_PER_USER, MAX_SUBMISSIONS_PER_DAY
from digitaltwins.ber.services.validation import validate_ber_experiment
from digitaltwins.ber.views.requester import _submit_dedup_key
from digitaltwins.models import BerExperimentRequest

from .ber_factories import VALID_EXPERIMENT, make_completed_request, make_request, make_user
from .fakes import SAMPLE_LP, fake_object_storage, queued_task_funcs

Status = BerExperimentRequest.Status
XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


def as_input(moment):
    return moment.strftime('%Y-%m-%dT%H:%M')


@override_settings(BER_EMAIL='ber-lab@example.com')
class SubmissionLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('limits@example.com')

    def setUp(self):
        self.client.force_login(self.user)

    def _submit(self, experiment=VALID_EXPERIMENT):
        return self.client.post(
            reverse('ber-hydrogen-submit'), data=json.dumps(experiment), content_type='application/json',
        )

    def test_pending_limit(self):
        for _ in range(MAX_PENDING_PER_USER):
            make_request(self.user)

        response = self._submit()

        self.assertEqual(response.status_code, 429)
        self.assertIn(f'{MAX_PENDING_PER_USER} requests waiting', response.json()['error'])
        self.assertEqual(BerExperimentRequest.objects.count(), MAX_PENDING_PER_USER)
        self.assertEqual(queued_task_funcs(), [], 'BER must not be emailed')

    def test_decided_requests_free_a_pending_slot(self):
        for _ in range(MAX_PENDING_PER_USER - 1):
            make_request(self.user)
        make_request(self.user, status=Status.REJECTED)

        self.assertEqual(self._submit().status_code, 202)

    def test_daily_limit_counts_cancelled_requests_too(self):
        for _ in range(MAX_SUBMISSIONS_PER_DAY):
            make_request(self.user, status=Status.CANCELLED)

        response = self._submit()

        self.assertEqual(response.status_code, 429)
        self.assertIn(f'at most {MAX_SUBMISSIONS_PER_DAY} experiment requests in 24 hours', response.json()['error'])

    def test_requests_older_than_a_day_do_not_count(self):
        for _ in range(MAX_SUBMISSIONS_PER_DAY):
            make_request(self.user, status=Status.CANCELLED)
        BerExperimentRequest.objects.update(created_at=datetime.now(timezone.utc) - timedelta(days=1, minutes=1))

        self.assertEqual(self._submit().status_code, 202)

    def test_limits_are_per_user(self):
        other = make_user('limits-other@example.com')
        for _ in range(MAX_PENDING_PER_USER):
            make_request(other)

        self.assertEqual(self._submit().status_code, 202)

    def test_a_refused_submission_can_be_retried_once_allowed(self):
        """The duplicate-submission guard must not remember a submission that created nothing."""
        pending = [make_request(self.user) for _ in range(MAX_PENDING_PER_USER)]
        self.assertEqual(self._submit().status_code, 429)

        self.client.post(reverse('ber-hydrogen-request-cancel', args=[pending[0].pk]))
        response = self._submit()

        self.assertEqual(response.status_code, 202)
        self.assertNotIn(response.json()['requestId'], [r.pk for r in pending])


class DuplicateSubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = make_user('dedup@example.com')

    def test_identical_submission_while_the_first_is_still_being_created(self):
        cleaned, _ = validate_ber_experiment(VALID_EXPERIMENT)
        cache.add(_submit_dedup_key(self.user.pk, cleaned), 0, timeout=30)  # the first one holds the claim
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('ber-hydrogen-submit'), data=json.dumps(VALID_EXPERIMENT), content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertFalse(BerExperimentRequest.objects.exists())


class ExecutionTimeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('times-staff@example.com', ber_staff=True)
        cls.requester = make_user('times-requester@example.com')

    def _complete(self, start, end):
        experiment_request = make_request(self.requester)
        self.client.force_login(self.staff)
        with fake_object_storage():
            response = self.client.post(reverse('ber-management-detail', args=[experiment_request.pk]), {
                'action': 'complete', 'actual_start': as_input(start), 'actual_end': as_input(end),
                'result_file': SimpleUploadedFile('r.lp', SAMPLE_LP),
            }, **XHR)
        experiment_request.refresh_from_db()
        return response, experiment_request

    def test_start_before_submission_is_refused(self):
        now = datetime.now(timezone.utc)
        response, experiment_request = self._complete(now - timedelta(days=1), now - timedelta(hours=23))

        self.assertEqual(response.status_code, 400)
        self.assertIn('cannot have started before the request was submitted', response.json()['error'])
        self.assertEqual(experiment_request.status, Status.PENDING)

    def test_end_in_the_future_is_refused(self):
        now = datetime.now(timezone.utc)
        response, experiment_request = self._complete(now, now + timedelta(hours=2))

        self.assertEqual(response.status_code, 400)
        self.assertIn('cannot be in the future', response.json()['error'])
        self.assertEqual(experiment_request.status, Status.PENDING)

    def test_end_a_few_minutes_ahead_is_tolerated(self):
        """Staff clocks drift; "just now" typed on a fast clock must still work."""
        now = datetime.now(timezone.utc)
        response, experiment_request = self._complete(now, now + timedelta(minutes=3))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(experiment_request.status, Status.COMPLETED)


class DeletedRequestFileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('delete-requester@example.com')

    def test_deleting_a_request_removes_its_result_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)

            with self.captureOnCommitCallbacks(execute=True):
                experiment_request.delete()

            self.assertEqual(storage.keys(), [])

    def test_deleting_the_requester_removes_their_result_files(self):
        user = make_user('leaving@example.com')
        with fake_object_storage() as storage:
            make_completed_request(user, storage, data=SAMPLE_LP)
            make_completed_request(user, storage, data=SAMPLE_LP, key='ber-hydrogen/other/result.lp')
            kept = make_completed_request(self.requester, storage, data=SAMPLE_LP)

            with self.captureOnCommitCallbacks(execute=True):
                user.delete()

            self.assertEqual(storage.keys(), [kept.result_key])

    def test_a_rolled_back_delete_keeps_the_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)
            pk = experiment_request.pk  # delete() sets the instance's pk to None

            with self.captureOnCommitCallbacks(execute=True):
                try:
                    with transaction.atomic():
                        experiment_request.delete()
                        raise RuntimeError('abort')
                except RuntimeError:
                    pass

            self.assertEqual(storage.keys(), [experiment_request.result_key])
            self.assertTrue(BerExperimentRequest.objects.filter(pk=pk).exists())


@override_settings(BER_EMAIL='ber-lab@example.com', PLATFORM_URL='https://dashboard.energy-guard.eu/')
class EmailLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('links@example.com')

    def test_links_use_platform_url_not_the_host_the_request_came_in_on(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)

        # Tasks queued before PLATFORM_URL still pass the old request-derived URL.
        import_string('digitaltwins.ber.tasks.notify_ber_request_decision')(
            experiment_request.pk, 'http://147.102.6.166/',
        )

        body = mail.outbox[0].body
        self.assertIn(
            f'https://dashboard.energy-guard.eu/digitaltwins/ber-hydrogen/ber-hydrogen-dt/requests/{experiment_request.pk}/',
            body,
        )
        self.assertNotIn('147.102.6.166', body)

    def test_submission_email_is_queued_without_a_url(self):
        self.client.force_login(self.requester)
        self.client.post(
            reverse('ber-hydrogen-submit'), data=json.dumps(VALID_EXPERIMENT), content_type='application/json',
            HTTP_HOST='147.102.6.166',
        )

        self.assertEqual(queued_task_funcs(), ['digitaltwins.ber.tasks.send_ber_notification_email'])
        experiment_request = BerExperimentRequest.objects.get()
        import_string('digitaltwins.ber.tasks.send_ber_notification_email')(experiment_request.pk)
        self.assertIn(settings.PLATFORM_URL, mail.outbox[0].body)
