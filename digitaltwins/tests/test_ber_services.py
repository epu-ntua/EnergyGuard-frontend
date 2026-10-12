"""The BER request state changes (digitaltwins.ber.services.requests), called directly.

The URL-level tests cover the normal flows; these cover what is hard to reach
through HTTP: two people acting at once, and a failure between the state change
and its notification.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.module_loading import import_string

from digitaltwins.ber.forms import REJECTION_REASON_MAX_WORDS
from digitaltwins.ber.services import requests as ber_requests
from digitaltwins.ber.services.requests import TransitionError
from digitaltwins.models import BerExperimentRequest

from .ber_factories import make_completed_request, make_request, make_user
from .fakes import SAMPLE_LP, fake_object_storage, queued_task_funcs

Status = BerExperimentRequest.Status
PLATFORM_URL = 'https://dashboard.example.com/'
START = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
ENQUEUE = 'digitaltwins.ber.services.requests.async_task'


def upload(data=SAMPLE_LP):
    return SimpleUploadedFile('result.lp', data)


def complete(experiment_request):
    ber_requests.complete_request(
        experiment_request, actual_start=START, actual_end=END, result_file=upload(), platform_url=PLATFORM_URL,
    )


class StateChangeAndNotificationAreAtomicTests(TestCase):
    """If queueing the notification fails, the state change must not stick either."""

    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('atomic-requester@example.com')
        cls.staff = make_user('atomic-staff@example.com', ber_staff=True)

    def test_failed_enqueue_leaves_the_request_pending_and_no_file_behind(self):
        experiment_request = make_request(self.requester)

        with fake_object_storage() as storage, patch(ENQUEUE, side_effect=DatabaseError('broker down')):
            with self.assertRaisesMessage(TransitionError, 'Could not save the decision'):
                complete(experiment_request)

        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.PENDING)
        self.assertEqual(experiment_request.result_key, '')
        self.assertEqual(storage.keys(), [])

    def test_failed_enqueue_on_replace_keeps_the_current_file(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)
            old_key = experiment_request.result_key

            with patch(ENQUEUE, side_effect=DatabaseError('broker down')):
                with self.assertRaisesMessage(TransitionError, 'Could not save the new result file'):
                    ber_requests.replace_result(
                        experiment_request, actor=self.staff, result_file=upload(), platform_url=PLATFORM_URL,
                    )

        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.result_key, old_key)
        self.assertEqual(storage.keys(), [old_key])

    def test_failed_enqueue_on_reject_leaves_the_request_pending(self):
        experiment_request = make_request(self.requester)

        with patch(ENQUEUE, side_effect=DatabaseError('broker down')), self.assertRaises(DatabaseError):
            ber_requests.reject_request(experiment_request, reason='No', platform_url=PLATFORM_URL)

        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.PENDING)

    @override_settings(BER_EMAIL='ber-lab@example.com')
    def test_failed_enqueue_on_submit_creates_no_request(self):
        with patch(ENQUEUE, side_effect=DatabaseError('broker down')), self.assertRaises(DatabaseError):
            ber_requests.submit_request(self.requester, [{'time': 0}], platform_url=PLATFORM_URL)

        self.assertFalse(BerExperimentRequest.objects.exists())

    def test_successful_decision_queues_exactly_its_notifications(self):
        experiment_request = make_request(self.requester)

        with fake_object_storage():
            complete(experiment_request)

        self.assertEqual(queued_task_funcs(), [
            'digitaltwins.ber.tasks.warm_ber_results_cache',
            'digitaltwins.ber.tasks.notify_ber_request_decision',
        ])


class ConcurrentChangeTests(TestCase):
    """The object in hand is stale: someone else changed the row since it was read."""

    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('race-requester@example.com')
        cls.staff = make_user('race-staff@example.com', ber_staff=True)

    def test_completing_a_request_the_requester_just_cancelled(self):
        experiment_request = make_request(self.requester)
        BerExperimentRequest.objects.filter(pk=experiment_request.pk).update(status=Status.CANCELLED)

        with fake_object_storage() as storage:
            with self.assertRaisesMessage(TransitionError, 'The requester cancelled this request.'):
                complete(experiment_request)

        self.assertEqual(storage.keys(), [], 'the uploaded file must be discarded')
        self.assertEqual(queued_task_funcs(), [])

    def test_rejecting_a_request_another_staff_member_just_completed(self):
        experiment_request = make_request(self.requester)
        BerExperimentRequest.objects.filter(pk=experiment_request.pk).update(status=Status.COMPLETED)

        with self.assertRaisesMessage(TransitionError, 'This request has already been decided.'):
            ber_requests.reject_request(experiment_request, reason='Too late', platform_url=PLATFORM_URL)

        self.assertEqual(queued_task_funcs(), [])

    def test_replacing_a_file_someone_else_just_replaced(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)
            BerExperimentRequest.objects.filter(pk=experiment_request.pk).update(result_key='ber-hydrogen/x/theirs.lp')

            with self.assertRaisesMessage(TransitionError, 'changed by someone else'):
                ber_requests.replace_result(
                    experiment_request, actor=self.staff, result_file=upload(), platform_url=PLATFORM_URL,
                )

            # Only the original file is left: this upload was discarded, theirs stands.
            self.assertEqual(storage.keys(), [f'ber-hydrogen/{experiment_request.pk}/result-existing.lp'])
        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.result_key, 'ber-hydrogen/x/theirs.lp')

    def test_cancelling_a_request_ber_just_decided_keeps_the_decision(self):
        experiment_request = make_request(self.requester)
        BerExperimentRequest.objects.filter(pk=experiment_request.pk).update(status=Status.REJECTED)

        self.assertFalse(ber_requests.cancel_request(experiment_request, platform_url=PLATFORM_URL))

        experiment_request.refresh_from_db()
        self.assertEqual(experiment_request.status, Status.REJECTED)


class SmallTransitionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('small-requester@example.com')
        cls.staff = make_user('small-staff@example.com', ber_staff=True)

    def test_restore_reports_whether_anything_changed(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)

        self.assertFalse(ber_requests.restore_request(experiment_request, actor=self.staff))
        ber_requests.archive_request(experiment_request, actor=self.staff)
        self.assertTrue(ber_requests.restore_request(experiment_request, actor=self.staff))

    def test_archiving_twice_says_so(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)
        ber_requests.archive_request(experiment_request, actor=self.staff)

        with self.assertRaisesMessage(TransitionError, 'already archived'):
            ber_requests.archive_request(experiment_request, actor=self.staff)

    def test_hide_only_finished_requests(self):
        self.assertFalse(ber_requests.hide_request(make_request(self.requester)))
        self.assertTrue(ber_requests.hide_request(make_request(self.requester, status=Status.CANCELLED)))


class RejectionReasonLengthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = make_user('words-staff@example.com', ber_staff=True)
        cls.requester = make_user('words-requester@example.com')

    def _reject(self, reason):
        experiment_request = make_request(self.requester)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse('ber-management-detail', args=[experiment_request.pk]),
            {'action': 'reject', 'rejection_reason': reason}, HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        experiment_request.refresh_from_db()
        return response, experiment_request

    def test_reason_at_the_word_limit_is_accepted(self):
        response, experiment_request = self._reject(' '.join(['word'] * REJECTION_REASON_MAX_WORDS))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(experiment_request.status, Status.REJECTED)

    def test_reason_over_the_word_limit_is_refused(self):
        response, experiment_request = self._reject(' '.join(['word'] * (REJECTION_REASON_MAX_WORDS + 1)))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['error'],
            f'The rejection reason can be at most {REJECTION_REASON_MAX_WORDS} words '
            f'(it has {REJECTION_REASON_MAX_WORDS + 1}).',
        )
        self.assertEqual(experiment_request.status, Status.PENDING)

    def test_reason_is_stored_without_surrounding_whitespace(self):
        _, experiment_request = self._reject('  Setpoints too aggressive \n')
        self.assertEqual(experiment_request.rejection_reason, 'Setpoints too aggressive')


class NotificationIndependenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('notify-requester@example.com')

    def test_email_still_goes_out_when_the_in_app_notification_fails(self):
        for path, status in [
            ('digitaltwins.ber.tasks.notify_ber_request_decision', Status.COMPLETED),
            ('digitaltwins.ber.tasks.notify_ber_results_updated', Status.COMPLETED),
        ]:
            with self.subTest(path=path):
                mail.outbox.clear()
                experiment_request = make_request(self.requester, status=status)

                with patch('accounts.models.Notification.objects.create', side_effect=DatabaseError('down')):
                    import_string(path)(experiment_request.pk, PLATFORM_URL)

                self.assertEqual(len(mail.outbox), 1)
                self.assertEqual(mail.outbox[0].to, [self.requester.email])
