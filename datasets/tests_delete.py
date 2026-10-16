"""dataset_delete removes the MinIO object at the key stored on the dataset.

It used to rebuild the path from the username and current name, which missed
the object (its folder uses the slugified username and the name at upload
time): the delete succeeded and the file stayed in MinIO.
"""

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset
from datasets.services import MinioUploadError

from .tests_access_control import make_dataset, make_user


@mock.patch('datasets.views.edit.delete_dataset_objects')
@mock.patch('datasets.views.edit.provision_user_datasets')
@mock.patch('datasets.views.edit.delete_dataset_cache')
class DatasetDeleteMinioTests(TestCase):
    def setUp(self):
        self.owner = make_user('jane.doe@example.com')
        self.dataset = make_dataset('old-name', self.owner, visibility=False)
        Dataset.objects.filter(pk=self.dataset.pk).update(
            name='Renamed since upload',
            data_file='user_janedoeexamplecom/old-name/data.csv',
        )
        self.dataset.refresh_from_db()
        self.client.force_login(self.owner)

    def test_deletes_the_stored_object_key(self, delete_cache, provision, delete_objects):
        self.client.post(reverse('dataset_delete', args=[self.dataset.pk]))

        delete_objects.assert_called_once_with(
            bucket_name='energyguard-datasets',
            data_file_key='user_janedoeexamplecom/old-name/data.csv',
        )
        self.assertFalse(Dataset.objects.filter(pk=self.dataset.pk).exists())

    def test_minio_failure_keeps_the_dataset_and_reprovisions_jupyterhub(self, delete_cache, provision, delete_objects):
        delete_objects.side_effect = MinioUploadError('down')

        self.client.post(reverse('dataset_delete', args=[self.dataset.pk]))

        provision.assert_called_once_with(
            'jane.doe@example.com', {'user_janedoeexamplecom/old-name': 'Renamed since upload'},
        )
        self.assertTrue(Dataset.objects.filter(pk=self.dataset.pk).exists())
