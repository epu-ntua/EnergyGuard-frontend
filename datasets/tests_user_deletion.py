"""A deleted account takes its datasets and their files with it.

publisher used to be SET_NULL: the rows stayed, their MinIO objects and JupyterHub
copies too, and a public one turned into platform-owned data - which counts as
published, even when a reviewer had rejected it.
"""

from unittest import mock

import requests
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset
from datasets.services import MinioUploadError
from datasets.tasks import discard_dataset_files

from .tests_access_control import make_dataset, make_user


@mock.patch('datasets.signals.async_task')
class UserDeletionTests(TestCase):
    def setUp(self):
        self.owner = make_user('leaving@example.com')
        self.other = make_user('stays@example.com')

    def test_deleting_the_user_deletes_their_datasets_and_queues_their_files(self, async_task):
        make_dataset('rejected-one', self.owner, visibility=True, status=Dataset.Status.REJECTED)
        make_dataset('theirs', self.other, visibility=False)
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()

        self.assertEqual(list(Dataset.objects.values_list('name', flat=True)), ['theirs'])
        self.assertFalse(Dataset.objects.published().filter(name='rejected-one').exists())
        async_task.assert_called_once_with(
            'datasets.tasks.discard_dataset_files',
            bucket_name='energyguard-datasets',
            data_file_key='user_x/rejected-one/data.csv',
            email='leaving@example.com',
            dataset_name='rejected-one',
        )

    def test_same_name_as_a_platform_dataset_does_not_block_the_delete(self, async_task):
        make_dataset('Grid Pilot Data', None, visibility=True)
        make_dataset('Grid Pilot Data', self.owner, visibility=False)
        self.owner.delete()
        self.assertEqual(Dataset.objects.filter(name='Grid Pilot Data', publisher__isnull=True).count(), 1)

    def test_rolled_back_delete_keeps_the_files(self, async_task):
        make_dataset('mine', self.owner, visibility=False)
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError), transaction.atomic():
                self.owner.delete()
                raise RuntimeError('Keycloak said no')
        self.assertTrue(Dataset.objects.filter(name='mine').exists())
        async_task.assert_not_called()

    def test_platform_dataset_files_are_never_touched(self, async_task):
        pilot = make_dataset('Grid Pilot Data', None, visibility=True)
        with self.captureOnCommitCallbacks(execute=True):
            pilot.delete()
        async_task.assert_not_called()

    @mock.patch('datasets.views.edit.delete_dataset_objects')
    @mock.patch('datasets.views.edit.delete_dataset_cache')
    def test_delete_button_removes_the_files_only_once(self, delete_cache, delete_objects, async_task):
        dataset = make_dataset('mine', self.owner, visibility=False)
        self.client.force_login(self.owner)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dataset_delete', args=[dataset.pk]))
        self.assertFalse(Dataset.objects.filter(pk=dataset.pk).exists())
        delete_objects.assert_called_once()
        async_task.assert_not_called()


@mock.patch('datasets.tasks.delete_dataset_cache')
@mock.patch('datasets.tasks.delete_dataset_objects')
class DiscardDatasetFilesTests(TestCase):
    def _discard(self, email='leaving@example.com'):
        discard_dataset_files(
            bucket_name='energyguard-datasets', data_file_key='user_x/mine/data.csv',
            email=email, dataset_name='mine',
        )

    def test_removes_the_object_and_the_jupyterhub_copy(self, delete_objects, delete_cache):
        self._discard()
        delete_objects.assert_called_once_with(bucket_name='energyguard-datasets', data_file_key='user_x/mine/data.csv')
        delete_cache.assert_called_once_with('leaving@example.com', 'mine')

    def test_failures_are_logged_not_raised(self, delete_objects, delete_cache):
        delete_objects.side_effect = MinioUploadError('down')
        delete_cache.side_effect = requests.ConnectionError('down')
        with self.assertLogs('datasets.tasks', level='ERROR') as logs:
            self._discard()
        self.assertIn('user_x/mine/data.csv', logs.output[0])
        delete_cache.assert_called_once()


@mock.patch('datasets.signals.async_task')
class SeedPilotDatasetsLeavesUserDatasetsAloneTests(TestCase):
    """seed_pilot_datasets looked pilot rows up by name alone, so a user's dataset
    named like one was deleted (now with its files) or turned into the pilot row."""

    def setUp(self):
        self.user_dataset = make_dataset('BER Pilot Data', make_user('jane@example.com'), visibility=False)

    def _seed(self, *, object_found):
        from django.core.management import call_command
        with mock.patch('datasets.management.commands.seed_pilot_datasets.object_exists', return_value=object_found), \
             mock.patch('datasets.management.commands.seed_pilot_datasets.get_object_size', return_value=1024), \
             self.captureOnCommitCallbacks(execute=True):
            call_command('seed_pilot_datasets', partner='BER', stdout=mock.MagicMock(), stderr=mock.MagicMock())

    def test_missing_pilot_file_does_not_delete_a_user_dataset(self, async_task):
        make_dataset('BER Pilot Data', None, visibility=True)
        self._seed(object_found=False)
        self.assertTrue(Dataset.objects.filter(pk=self.user_dataset.pk).exists())
        self.assertFalse(Dataset.objects.filter(name='BER Pilot Data', publisher__isnull=True).exists())
        async_task.assert_not_called()

    def test_seeding_does_not_take_over_a_user_dataset(self, async_task):
        self._seed(object_found=True)
        self.user_dataset.refresh_from_db()
        self.assertEqual(self.user_dataset.data_file, 'user_x/BER Pilot Data/data.csv')
        self.assertTrue(Dataset.objects.filter(name='BER Pilot Data', publisher__isnull=True).exists())
