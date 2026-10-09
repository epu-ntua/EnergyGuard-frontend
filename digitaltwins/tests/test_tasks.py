"""Background tasks, addressed by the dotted paths django_q stores.

Queued tasks and Schedule rows (including the one created by migration 0004)
keep these paths in the database, so they must stay importable no matter where
the implementation lives.
"""

from django.core import mail
from django.test import TestCase, override_settings
from django.utils.module_loading import import_string

from accounts.models import Notification
from digitaltwins.models import BerExperimentRequest

from .ber_factories import make_completed_request, make_request, make_user
from .fakes import SAMPLE_LP, fake_object_storage

Status = BerExperimentRequest.Status
PLATFORM_URL = 'https://dashboard.example.com/'

BER_TASKS = [
    'send_ber_notification_email',
    'send_ber_cancellation_email',
    'warm_ber_results_cache',
    'notify_ber_request_decision',
    'notify_ber_results_updated',
]

TASK_PATHS = [
    'digitaltwins.tasks.poll_rdn_job',
    'digitaltwins.tasks.reconcile_stale_rdn_jobs',
    *(f'digitaltwins.ber.tasks.{name}' for name in BER_TASKS),
    # Pre-move paths, possibly still on queued tasks: re-exported by digitaltwins.tasks.
    *(f'digitaltwins.tasks.{name}' for name in BER_TASKS),
]


def run(path, *args):
    return import_string(path)(*args)


class TaskPathTests(TestCase):
    def test_every_stored_task_path_is_importable(self):
        for path in TASK_PATHS:
            with self.subTest(path=path):
                self.assertTrue(callable(import_string(path)))

    def test_old_ber_paths_run_the_same_functions(self):
        for name in BER_TASKS:
            with self.subTest(name=name):
                self.assertIs(
                    import_string(f'digitaltwins.tasks.{name}'), import_string(f'digitaltwins.ber.tasks.{name}'),
                )


@override_settings(BER_EMAIL='ber-lab@example.com')
class BerTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.requester = make_user('task-requester@example.com')

    def test_new_request_email_goes_to_ber_with_the_management_link(self):
        experiment_request = make_request(self.requester)

        run('digitaltwins.ber.tasks.send_ber_notification_email', experiment_request.pk, PLATFORM_URL)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ber-lab@example.com'])
        self.assertIn(
            f'https://dashboard.example.com/digitaltwins/ber-hydrogen/ber-hydrogen-dt/management/{experiment_request.pk}/',
            mail.outbox[0].body,
        )

    @override_settings(BER_EMAIL='')
    def test_no_ber_email_without_an_address(self):
        experiment_request = make_request(self.requester)
        run('digitaltwins.ber.tasks.send_ber_notification_email', experiment_request.pk, PLATFORM_URL)
        self.assertEqual(mail.outbox, [])

    def test_cancellation_email_goes_to_ber(self):
        experiment_request = make_request(self.requester, status=Status.CANCELLED)

        run('digitaltwins.ber.tasks.send_ber_cancellation_email', experiment_request.pk, PLATFORM_URL)

        self.assertEqual(mail.outbox[0].to, ['ber-lab@example.com'])
        self.assertIn('cancelled', mail.outbox[0].subject)

    def test_completion_notifies_the_requester_in_app_and_by_email(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)

        run('digitaltwins.ber.tasks.notify_ber_request_decision', experiment_request.pk, PLATFORM_URL)

        notification = Notification.objects.get(recipient=self.requester)
        self.assertEqual(notification.url, f'/digitaltwins/ber-hydrogen/ber-hydrogen-dt/requests/{experiment_request.pk}/')
        self.assertEqual(mail.outbox[0].to, [self.requester.email])
        self.assertIn('is complete', mail.outbox[0].subject)

    def test_rejection_email_carries_the_reason(self):
        experiment_request = make_request(self.requester, status=Status.REJECTED, rejection_reason='Out of range')

        run('digitaltwins.ber.tasks.notify_ber_request_decision', experiment_request.pk, PLATFORM_URL)

        self.assertIn('was rejected', mail.outbox[0].subject)
        self.assertIn('Reason: Out of range', mail.outbox[0].body)

    def test_no_decision_notification_for_a_pending_request(self):
        experiment_request = make_request(self.requester)

        run('digitaltwins.ber.tasks.notify_ber_request_decision', experiment_request.pk, PLATFORM_URL)

        self.assertFalse(Notification.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_results_updated_notifies_the_requester(self):
        experiment_request = make_request(self.requester, status=Status.COMPLETED)

        run('digitaltwins.ber.tasks.notify_ber_results_updated', experiment_request.pk, PLATFORM_URL)

        self.assertEqual(Notification.objects.get(recipient=self.requester).icon, 'rotate')
        self.assertIn('Updated results', mail.outbox[0].subject)

    def test_warming_fills_the_results_cache(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=SAMPLE_LP)

            run('digitaltwins.ber.tasks.warm_ber_results_cache', experiment_request.pk)
            storage.fail_reads = True

            self.client.force_login(self.requester)
            response = self.client.get(f'/digitaltwins/ber-hydrogen/ber-hydrogen-dt/requests/{experiment_request.pk}/')

        self.assertTemplateUsed(response, 'digitaltwins/ber-hydrogen-results.html')

    def test_warming_an_unreadable_file_does_not_raise(self):
        with fake_object_storage() as storage:
            experiment_request = make_completed_request(self.requester, storage, data=b'garbage\n')
            run('digitaltwins.ber.tasks.warm_ber_results_cache', experiment_request.pk)

    def test_tasks_tolerate_a_deleted_request(self):
        for path, args in [
            ('digitaltwins.ber.tasks.send_ber_notification_email', (999999, PLATFORM_URL)),
            ('digitaltwins.ber.tasks.send_ber_cancellation_email', (999999, PLATFORM_URL)),
            ('digitaltwins.ber.tasks.notify_ber_request_decision', (999999, PLATFORM_URL)),
            ('digitaltwins.ber.tasks.notify_ber_results_updated', (999999, PLATFORM_URL)),
            ('digitaltwins.ber.tasks.warm_ber_results_cache', (999999,)),
        ]:
            with self.subTest(path=path):
                run(path, *args)
        self.assertEqual(mail.outbox, [])
