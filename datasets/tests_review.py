"""Tests for the dataset publication review workflow."""

import html
import re
from datetime import timedelta
from importlib import import_module
from unittest import mock

from django.apps import apps

from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification
from datasets import tasks
from datasets.forms import GeneralDatasetForm
from datasets.models import Dataset
from datasets.services.review import apply_edit, submit_new_upload

from .tests_access_control import make_dataset, make_user

Status = Dataset.Status


def flash_messages(response):
    return ' '.join(str(message) for message in response.wsgi_request._messages)


def grant_review(user):
    user.user_permissions.add(Permission.objects.get(codename='review_dataset'))


class ReviewVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('owner@example.com')
        cls.other = make_user('other@example.com')
        cls.reviewer = make_user('reviewer@example.com')
        grant_review(cls.reviewer)

        cls.pending = make_dataset('pending-set', cls.owner, visibility=True, status=Status.UNDER_REVIEW)
        cls.rejected = make_dataset('rejected-set', cls.owner, visibility=True, status=Status.REJECTED)
        cls.approved = make_dataset('approved-set', cls.owner, visibility=True)
        cls.private = make_dataset('private-set', cls.owner, visibility=False, status=Status.UNDER_REVIEW)
        cls.platform = Dataset.objects.create(
            name='platform-set', publisher=None, visibility=True, size_gb='1.00',
        )

    def test_published_lists_approved_and_platform_datasets_only(self):
        self.assertCountEqual(Dataset.objects.published(), [self.approved, self.platform])

    def test_awaiting_review_lists_public_pending_user_datasets(self):
        self.assertCountEqual(Dataset.objects.awaiting_review(), [self.pending])

    def test_other_user_sees_only_published(self):
        visible = Dataset.objects.visible_to(self.other)
        self.assertCountEqual(visible, [self.approved, self.platform])
        for dataset in (self.pending, self.rejected, self.private):
            self.assertFalse(dataset.is_accessible_by(self.other))

    def test_publisher_sees_own_datasets_in_every_state(self):
        visible = Dataset.objects.visible_to(self.owner)
        for dataset in (self.pending, self.rejected, self.approved, self.private):
            self.assertIn(dataset, visible)
            self.assertTrue(dataset.is_accessible_by(self.owner))

    def test_reviewer_sees_submitted_but_not_private(self):
        visible = Dataset.objects.visible_to(self.reviewer)
        self.assertIn(self.pending, visible)
        self.assertIn(self.rejected, visible)
        self.assertNotIn(self.private, visible)
        self.assertTrue(self.pending.is_accessible_by(self.reviewer))
        self.assertFalse(self.private.is_accessible_by(self.reviewer))

    def test_public_tab_includes_own_published_datasets(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('datasets_list_json'), {'scope': 'public', 'draw': 1, 'start': 0, 'length': 50})
        names = {row[0] for row in response.json()['data']}
        self.assertEqual(names, {'approved-set', 'platform-set'})

    def test_pending_dataset_is_not_in_public_tab(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('datasets_list_json'), {'scope': 'public', 'draw': 1, 'start': 0, 'length': 50})
        names = {row[0] for row in response.json()['data']}
        self.assertEqual(names, {'approved-set', 'platform-set'})

    def test_my_tab_carries_status(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('datasets_list_json'), {'scope': 'my', 'draw': 1, 'start': 0, 'length': 50})
        # Rows are positional: [..., status, id].
        statuses = {row[0]: row[-2] for row in response.json()['data']}
        self.assertEqual(statuses, {
            'pending-set': 'under_review',
            'rejected-set': 'rejected',
            'approved-set': 'published',
            'private-set': 'private',
        })

    def test_stranger_cannot_open_pending_dataset(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('dataset_details', args=[self.pending.pk]))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)


@mock.patch('datasets.services.review.async_task')
class ReviewDecisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('owner@example.com')
        cls.reviewer = make_user('reviewer@example.com')
        grant_review(cls.reviewer)

    def setUp(self):
        self.dataset = make_dataset('pending-set', self.owner, visibility=True, status=Status.UNDER_REVIEW)

    def decide(self, name, version=None, **data):
        """POST a decision on the version currently in the database (what the
        reviewer's page would carry) unless `version` says otherwise."""
        if version is None:
            version = Dataset.objects.get(pk=self.dataset.pk).updated_at.isoformat()
        return self.client.post(reverse(name, args=[self.dataset.pk]), {'version': version, **data})

    def test_non_reviewer_cannot_decide(self, async_task):
        self.client.force_login(self.owner)
        for name in ('dataset_approve', 'dataset_reject'):
            response = self.decide(name, rejection_reason='x')
            self.assertEqual(response.status_code, 403)
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)
        async_task.assert_not_called()

    def test_approve(self, async_task):
        self.client.force_login(self.reviewer)
        self.decide('dataset_approve')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.APPROVED)
        self.assertEqual(self.dataset.reviewed_by, self.reviewer)
        self.assertIsNotNone(self.dataset.reviewed_at)
        async_task.assert_called_once_with('datasets.tasks.notify_dataset_review_decision', self.dataset.pk)

    def test_second_decision_is_refused(self, async_task):
        self.client.force_login(self.reviewer)
        self.decide('dataset_approve')
        self.decide('dataset_reject', rejection_reason='late')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.APPROVED)
        self.assertEqual(async_task.call_count, 1)

    def test_reject_requires_reason(self, async_task):
        self.client.force_login(self.reviewer)
        self.decide('dataset_reject', rejection_reason='   ')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)
        async_task.assert_not_called()

    def test_reject_stores_reason(self, async_task):
        self.client.force_login(self.reviewer)
        self.decide('dataset_reject', rejection_reason=' Missing units. ')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.REJECTED)
        self.assertEqual(self.dataset.rejection_reason, 'Missing units.')
        async_task.assert_called_once()

    def test_private_dataset_cannot_be_approved(self, async_task):
        self.dataset.visibility = False
        self.dataset.save()
        self.client.force_login(self.reviewer)
        self.decide('dataset_approve')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)
        async_task.assert_not_called()

    def test_decision_on_a_version_edited_since_is_refused(self, async_task):
        seen_version = self.dataset.updated_at.isoformat()
        # The publisher edits the description while the reviewer has the page open.
        self.client.force_login(self.owner)
        self.client.post(reverse('dataset_edit', args=[self.dataset.pk]), {
            'name': self.dataset.name, 'description': 'Swapped text', 'label': self.dataset.label, 'visibility': 'on',
        })
        self.client.force_login(self.reviewer)
        response = self.decide('dataset_approve', version=seen_version)
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)
        self.assertIn('changed after you opened it', flash_messages(response))
        async_task.assert_not_called()

    def test_decision_without_version_is_refused(self, async_task):
        self.client.force_login(self.reviewer)
        self.client.post(reverse('dataset_approve', args=[self.dataset.pk]))
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)

    def test_stale_edit_form_does_not_undo_approval(self, async_task):
        # The publisher's request loads the dataset while it is under review...
        stale = Dataset.objects.get(pk=self.dataset.pk)
        form = GeneralDatasetForm({
            'name': stale.name, 'description': stale.description, 'label': stale.label, 'visibility': 'on',
        }, instance=stale)
        self.assertTrue(form.is_valid())
        # ...a reviewer approves before it saves...
        self.client.force_login(self.reviewer)
        self.decide('dataset_approve')
        # ...and the unchanged form is saved afterwards.
        apply_edit(form, was_awaiting_review=True)
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.APPROVED)
        self.assertEqual(self.dataset.reviewed_by, self.reviewer)

    def test_review_queue_is_ordered_by_submission(self, async_task):
        older_upload = make_dataset('older-upload', self.owner, visibility=True, status=Status.UNDER_REVIEW)
        Dataset.objects.filter(pk=older_upload.pk).update(
            created_at=timezone.now() - timedelta(days=365), submitted_at=timezone.now(),
        )
        Dataset.objects.filter(pk=self.dataset.pk).update(submitted_at=timezone.now() - timedelta(days=1))
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('dataset_review_list'))
        self.assertEqual([d.name for d in response.context['page_obj']], ['pending-set', 'older-upload'])

    def test_review_list_is_reviewer_only(self, async_task):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('dataset_review_list')).status_code, 403)
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('dataset_review_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['page_obj']), [self.dataset])

    def test_making_dataset_public_notifies_reviewers(self, async_task):
        self.dataset.visibility = False
        self.dataset.save()
        self.client.force_login(self.owner)
        data = {'name': self.dataset.name, 'description': '', 'label': self.dataset.label, 'visibility': 'on'}
        self.client.post(reverse('dataset_edit', args=[self.dataset.pk]), data)
        async_task.assert_called_once_with('datasets.tasks.notify_dataset_submitted', self.dataset.pk)

        # Saving again while still public does not re-notify.
        async_task.reset_mock()
        self.client.post(reverse('dataset_edit', args=[self.dataset.pk]), data)
        async_task.assert_not_called()


@override_settings(PLATFORM_URL='https://platform.test/')
class ReviewNotificationTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('owner@example.com')
        cls.direct_reviewer = make_user('direct@example.com')
        grant_review(cls.direct_reviewer)
        cls.group_reviewer = make_user('group@example.com')
        group = Group.objects.create(name='Dataset Reviewers')
        group.permissions.add(Permission.objects.get(codename='review_dataset'))
        cls.group_reviewer.groups.add(group)
        make_user('bystander@example.com')

    def test_submitted_notifies_every_reviewer(self):
        dataset = make_dataset('pending-set', self.owner, visibility=True, status=Status.UNDER_REVIEW)
        tasks.notify_dataset_submitted(dataset.pk)

        recipients = set(Notification.objects.values_list('recipient__email', flat=True))
        self.assertEqual(recipients, {'direct@example.com', 'group@example.com'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(mail.outbox[0].to, ['direct@example.com', 'group@example.com'])
        self.assertIn(f'https://platform.test/datasets/dataset/{dataset.pk}/', mail.outbox[0].body)

    def test_submitted_skips_dataset_no_longer_awaiting(self):
        dataset = make_dataset('approved-set', self.owner, visibility=True)
        tasks.notify_dataset_submitted(dataset.pk)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_rejection_notifies_publisher_with_reason(self):
        dataset = make_dataset('rejected-set', self.owner, visibility=True, status=Status.REJECTED)
        dataset.rejection_reason = 'Missing units.'
        dataset.save()
        tasks.notify_dataset_review_decision(dataset.pk)

        notification = Notification.objects.get()
        self.assertEqual(notification.recipient, self.owner)
        self.assertIn('rejected', notification.message)
        self.assertEqual(mail.outbox[0].to, ['owner@example.com'])
        self.assertIn('Missing units.', mail.outbox[0].body)


class ReviewDetailsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('owner@example.com')
        cls.reviewer = make_user('reviewer@example.com')
        grant_review(cls.reviewer)

    def test_reviewer_sees_decision_buttons_on_pending_dataset(self):
        dataset = make_dataset('pending-set', self.owner, visibility=True, status=Status.UNDER_REVIEW)
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('dataset_details', args=[dataset.pk]))
        self.assertContains(response, reverse('dataset_approve', args=[dataset.pk]))
        self.assertContains(response, reverse('dataset_reject', args=[dataset.pk]))

    def test_publisher_sees_rejection_reason_but_no_buttons(self):
        dataset = make_dataset('rejected-set', self.owner, visibility=True, status=Status.REJECTED)
        dataset.rejection_reason = 'Missing <b>units</b>.'
        dataset.save()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('dataset_details', args=[dataset.pk]))
        self.assertContains(response, 'Publication rejected')
        self.assertContains(response, 'Missing &lt;b&gt;units&lt;/b&gt;.')
        self.assertNotContains(response, reverse('dataset_approve', args=[dataset.pk]))


@mock.patch('datasets.services.review.async_task')
class ReReviewOnEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('owner@example.com')
        cls.reviewer = make_user('reviewer@example.com')
        cls.other = make_user('other@example.com')

    def setUp(self):
        self.dataset = make_dataset('approved-set', self.owner, visibility=True)
        Dataset.objects.filter(pk=self.dataset.pk).update(reviewed_by=self.reviewer, reviewed_at='2026-10-01T10:00Z')
        self.client.force_login(self.owner)

    def edit(self, **changes):
        data = {'name': self.dataset.name, 'description': self.dataset.description,
                'label': self.dataset.label, 'visibility': 'on' if self.dataset.visibility else ''}
        data.update(changes)
        if not data['visibility']:
            del data['visibility']  # an unchecked checkbox is not posted
        return self.client.post(reverse('dataset_edit', args=[self.dataset.pk]), data)

    def test_editing_approved_dataset_reopens_review(self, async_task):
        self.edit(description='New description')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)
        self.assertIsNone(self.dataset.reviewed_by)
        self.assertIsNone(self.dataset.reviewed_at)
        self.assertNotIn(self.dataset, Dataset.objects.visible_to(self.other))
        async_task.assert_called_once_with('datasets.tasks.notify_dataset_submitted', self.dataset.pk)

    def test_saving_without_changes_keeps_approval(self, async_task):
        self.edit()
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.APPROVED)
        async_task.assert_not_called()

    def test_republishing_approved_dataset_reopens_review(self, async_task):
        self.edit(visibility='')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.APPROVED)
        async_task.assert_not_called()

        self.edit(visibility='on')
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.UNDER_REVIEW)
        async_task.assert_called_once_with('datasets.tasks.notify_dataset_submitted', self.dataset.pk)

    def test_reopened_review_records_submission_time(self, async_task):
        self.edit(description='New description')
        self.dataset.refresh_from_db()
        self.assertIsNotNone(self.dataset.submitted_at)

    def test_editing_rejected_dataset_keeps_it_rejected(self, async_task):
        Dataset.objects.filter(pk=self.dataset.pk).update(status=Status.REJECTED, rejection_reason='No units.')
        self.dataset.refresh_from_db()
        response = self.edit(description='Added units')
        self.assertIn('remains hidden', flash_messages(response))
        self.dataset.refresh_from_db()
        self.assertEqual(self.dataset.status, Status.REJECTED)
        async_task.assert_not_called()


@mock.patch('datasets.services.review.async_task')
class SubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user('owner@example.com')

    def test_public_upload_is_submitted(self, async_task):
        dataset = make_dataset('public-upload', self.owner, visibility=True, status=Status.UNDER_REVIEW)
        submit_new_upload(dataset)
        dataset.refresh_from_db()
        self.assertIsNotNone(dataset.submitted_at)
        async_task.assert_called_once_with('datasets.tasks.notify_dataset_submitted', dataset.pk)

    def test_private_upload_is_not_submitted(self, async_task):
        dataset = make_dataset('private-upload', self.owner, visibility=False, status=Status.UNDER_REVIEW)
        submit_new_upload(dataset)
        dataset.refresh_from_db()
        self.assertIsNone(dataset.submitted_at)
        async_task.assert_not_called()


class BackfillSubmittedAtMigrationTests(TestCase):
    def test_public_user_datasets_get_upload_date_and_keep_status(self):
        owner = make_user('owner@example.com')
        public = make_dataset('was-public', owner, visibility=True, status=Status.UNDER_REVIEW)
        private = make_dataset('was-private', owner, visibility=False, status=Status.UNDER_REVIEW)

        import_module('datasets.migrations.0015_dataset_submitted_at').backfill_submitted_at(apps, None)

        public.refresh_from_db()
        private.refresh_from_db()
        # Still waiting for a reviewer: nothing is approved automatically.
        self.assertEqual(public.status, Status.UNDER_REVIEW)
        self.assertEqual(public.submitted_at, public.created_at)
        self.assertIsNone(private.submitted_at)


@mock.patch('datasets.services.review.async_task')
class ReviewRoundTripTests(TestCase):
    def test_version_rendered_on_the_page_is_accepted(self, async_task):
        owner = make_user('owner@example.com')
        reviewer = make_user('reviewer@example.com')
        grant_review(reviewer)
        dataset = make_dataset('pending-set', owner, visibility=True, status=Status.UNDER_REVIEW)

        self.client.force_login(reviewer)
        page = self.client.get(reverse('dataset_details', args=[dataset.pk])).content.decode()
        version = re.search(r'name="version" value="([^"]+)"', page).group(1)
        self.client.post(reverse('dataset_approve', args=[dataset.pk]), {'version': html.unescape(version)})

        dataset.refresh_from_db()
        self.assertEqual(dataset.status, Status.APPROVED)
