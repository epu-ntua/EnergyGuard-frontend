import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from datasets import forms as forms_module
from datasets.forms import FileUploadPlaceholderForm, MetadataDatasetForm
from datasets.tasks import finalize_dataset_upload
from datasets.views import AddDatasetView


class MetadataDatasetFormTests(SimpleTestCase):
    def test_manual_rows_build_expected_metadata_json(self):
        form = MetadataDatasetForm(
            data={
                "metadata_rows": json.dumps(
                    [
                        {
                            "feature_name": "distance",
                            "feature_unit": "m",
                            "feature_description": "distance between 2 points",
                        }
                    ]
                )
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["metadata"],
            {"distance": ["m", "distance between 2 points"]},
        )

    def test_file_and_rows_together_are_rejected(self):
        form = MetadataDatasetForm(
            data={
                "metadata_rows": json.dumps(
                    [
                        {
                            "feature_name": "distance",
                            "feature_unit": "m",
                            "feature_description": "distance between 2 points",
                        }
                    ]
                )
            },
            files={
                "metadata_file": SimpleUploadedFile(
                    "metadata.json",
                    b'{"distance": ["m", "distance between 2 points"]}',
                    content_type="application/json",
                )
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Choose one metadata input method",
            str(form.non_field_errors()),
        )


class FileUploadPlaceholderFormTests(SimpleTestCase):
    """Step 2 of the wizard.

    The browser now PUTs straight to MinIO with a presigned URL, so this form
    carries the resulting object key rather than the file itself. It replaced
    FileUploadDatasetForm; this module still imported that removed class, so the
    whole file failed to import and none of its tests ever ran.
    """

    def _payload(self, **overrides):
        data = {
            "upload_key": "pending/demo/abc123/dataset.csv",
            "bucket_name": "energyguard-datasets",
            "file_size_bytes": 1024,
            "original_filename": "dataset.csv",
            "content_type": "text/csv",
        }
        data.update(overrides)
        return data

    def test_valid_presigned_upload_metadata_is_accepted(self):
        form = FileUploadPlaceholderForm(data=self._payload())
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_upload_key_is_rejected(self):
        form = FileUploadPlaceholderForm(data=self._payload(upload_key="   "))
        self.assertFalse(form.is_valid())
        self.assertIn("upload_key", form.errors)

    def test_oversized_file_is_rejected(self):
        oversized = (forms_module._MAX_DATA_FILE_SIZE_MB * 1024 * 1024) + 1
        form = FileUploadPlaceholderForm(data=self._payload(file_size_bytes=oversized))
        self.assertFalse(form.is_valid())
        self.assertIn("file_size_bytes", form.errors)


class AddDatasetViewDoneTests(SimpleTestCase):
    """The wizard's final step.

    The upload itself no longer happens here: the browser PUTs to MinIO with a
    presigned URL, and `done()` only hands the object key to a background task.
    These tests replaced ones written against the old synchronous flow, which
    patched `upload_dataset_objects` / `delete_dataset_objects` - symbols this
    module removed, so the tests could not even be collected.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        request = self.factory.post("/datasets/dataset-upload/")
        request.user = SimpleNamespace(
            pk=1,
            username="demo",
            email="demo@example.com",
            get_full_name=lambda: "Demo User",
        )
        request.session = {}
        return request

    def _step_data(self, *, file_size_bytes=2 * 1024 ** 3):
        return {
            "general_info": {
                "name": "Demo dataset",
                "description": "Demo",
                "label": "renewable_energy",
                "visibility": True,
            },
            "upload_files": {
                "upload_key": "pending/demo/abc123/dataset.csv",
                "bucket_name": "energyguard-datasets",
                "file_size_bytes": file_size_bytes,
            },
            "metadata": {
                "metadata": {"distance": ["m", "distance between 2 points"]},
            },
        }

    def _run_done(self, step_data):
        view = AddDatasetView()
        view.request = self._request()
        with patch("datasets.views.upload.async_task") as mock_async_task,              patch.object(
                 AddDatasetView,
                 "get_cleaned_data_for_step",
                 side_effect=lambda step: step_data[step],
             ):
            response = view.done(form_list=[])
        return response, mock_async_task, view.request

    def test_done_enqueues_finalisation_instead_of_uploading_inline(self):
        step_data = self._step_data()
        response, mock_async_task, request = self._run_done(step_data)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dataset-upload-success"))
        self.assertTrue(request.session["dataset_upload_success"])

        mock_async_task.assert_called_once()
        args, kwargs = mock_async_task.call_args
        self.assertIs(args[0], finalize_dataset_upload)
        self.assertEqual(kwargs["object_key"], "pending/demo/abc123/dataset.csv")
        self.assertEqual(kwargs["bucket_name"], "energyguard-datasets")
        self.assertEqual(kwargs["user_id"], 1)
        self.assertEqual(kwargs["user_email"], "demo@example.com")
        self.assertEqual(kwargs["dataset_name"], "Demo dataset")
        self.assertEqual(kwargs["dataset_visibility"], True)
        self.assertEqual(
            kwargs["dataset_metadata"],
            {"distance": ["m", "distance between 2 points"]},
        )

    def test_done_converts_byte_size_to_gigabytes(self):
        step_data = self._step_data(file_size_bytes=2 * 1024 ** 3)
        _, mock_async_task, _ = self._run_done(step_data)
        self.assertEqual(mock_async_task.call_args.kwargs["dataset_size_gb"], Decimal("2.00"))

    def test_done_floors_tiny_uploads_to_the_minimum_recorded_size(self):
        # size_gb has a MinValueValidator of 0.01, so a 1 KB file must not round to 0.
        step_data = self._step_data(file_size_bytes=1024)
        _, mock_async_task, _ = self._run_done(step_data)
        self.assertEqual(mock_async_task.call_args.kwargs["dataset_size_gb"], Decimal("0.01"))
