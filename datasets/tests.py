import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from datasets.forms import MetadataDatasetForm
from datasets.services.minio_storage import _is_fake_upload_enabled
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


class AddDatasetViewDoneTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("datasets.views.upload.transaction.atomic")
    @patch("datasets.views.upload.Dataset.objects.create")
    @patch("datasets.views.upload.upload_dataset_objects")
    def test_done_passes_manual_metadata_to_dataset_create(
        self,
        mock_upload_dataset_objects,
        mock_dataset_create,
        mock_transaction_atomic,
    ):
        data_file = SimpleUploadedFile(
            "dataset.csv",
            b"distance,temperature\n10,20\n",
            content_type="text/csv",
        )
        manual_metadata = {"distance": ["m", "distance between 2 points"]}
        mock_transaction_atomic.return_value.__enter__.return_value = None
        mock_transaction_atomic.return_value.__exit__.return_value = None

        mock_upload_dataset_objects.return_value = {
            "bucket_name": "datasets",
            "data_file_key": "user_demo/dataset_demo/data.csv",
            "metadata_file_key": "user_demo/dataset_demo/metadata.json",
        }

        request = self.factory.post("/datasets/dataset-upload/")
        request.user = SimpleNamespace(username="demo", pk=1)

        view = AddDatasetView()
        view.request = request

        step_data = {
            "general_info": {
                "name": "Demo dataset",
                "description": "Demo",
                "label": "renewable_energy",
                "visibility": True,
            },
            "upload_files": {
                "data_file": data_file,
            },
            "metadata": {
                "metadata_file": None,
                "metadata": manual_metadata,
            },
        }

        with patch.object(
            AddDatasetView,
            "get_cleaned_data_for_step",
            side_effect=lambda step: step_data[step],
        ):
            response = view.done(form_list=[])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dataset-upload-success"))
        self.assertEqual(mock_dataset_create.call_count, 1)
        self.assertEqual(
            mock_dataset_create.call_args.kwargs["metadata"],
            manual_metadata,
        )


class MinioSettingsTests(SimpleTestCase):
    @override_settings(OBJECT_STORAGE_FAKE_UPLOAD="False")
    def test_fake_upload_flag_false_string_is_false(self):
        self.assertFalse(_is_fake_upload_enabled())

    @override_settings(OBJECT_STORAGE_FAKE_UPLOAD="true")
    def test_fake_upload_flag_true_string_is_true(self):
        self.assertTrue(_is_fake_upload_enabled())
