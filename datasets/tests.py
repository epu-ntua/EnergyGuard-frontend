import io
import json
import zipfile
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from datasets import forms as forms_module
from datasets.forms import FileUploadPlaceholderForm, MetadataDatasetForm
from datasets.models import Dataset
from datasets.services.zip_archive import (
    CSV_IS_ZIP,
    ZIP_INVALID,
    ZIP_NO_CSV,
    ZIP_NON_CSV,
    check_uploaded_file,
    csv_entries,
    zip_contents_problem,
)
from datasets.tasks import finalize_dataset_upload
from datasets.views import AddDatasetView
from datasets.views.details import metadata_table


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


class ZipContentsRuleTests(SimpleTestCase):
    """A dataset ZIP holds CSV files only (folders allowed), and at least one."""

    def test_csv_files_in_folders_are_accepted(self):
        self.assertIsNone(zip_contents_problem(["a.csv", "sub/", "sub/b.CSV"]))

    def test_macos_metadata_is_ignored(self):
        names = ["a.csv", "__MACOSX/", "__MACOSX/._a.csv", "sub/.DS_Store", "sub/._b.csv"]
        self.assertIsNone(zip_contents_problem(names))

    def test_any_non_csv_file_is_refused(self):
        self.assertEqual(zip_contents_problem(["a.csv", "README.md"]), ZIP_NON_CSV)

    def test_archive_without_csv_is_refused(self):
        self.assertEqual(zip_contents_problem(["sub/", "__MACOSX/._x"]), ZIP_NO_CSV)
        self.assertEqual(zip_contents_problem([]), ZIP_NO_CSV)

    def test_csv_entries_skip_macos_copies(self):
        self.assertEqual(csv_entries(["__MACOSX/._a.csv", "._b.csv", "a.csv"]), ["a.csv"])


class FinalizeRefusesBadZipTests(SimpleTestCase):
    KWARGS = dict(
        object_key="pending/alice/abc/data.zip",
        bucket_name="datasets",
        user_id=1,
        user_email="alice@example.com",
        user_display_name="Alice",
        dataset_name="My data",
        dataset_label="energy",
        dataset_visibility=False,
        dataset_description="",
        dataset_size_gb=Decimal("0.01"),
        dataset_metadata=None,
        site_url="https://platform.test/",
    )

    @patch("datasets.tasks.Dataset.objects.create")
    @patch("datasets.tasks._send_notification_email")
    @patch("datasets.tasks.delete_dataset_objects")
    @patch("datasets.tasks.check_uploaded_file", return_value=ZIP_NON_CSV)
    @patch("datasets.tasks.object_exists", return_value=True)
    def test_refused_zip_is_deleted_and_user_told_why(
        self, _exists, _check, mock_delete, mock_email, mock_create
    ):
        finalize_dataset_upload(**self.KWARGS)

        mock_create.assert_not_called()
        mock_delete.assert_called_once_with(
            bucket_name="datasets", data_file_key="pending/alice/abc/data.zip"
        )
        self.assertFalse(mock_email.call_args.kwargs["success"])
        self.assertEqual(mock_email.call_args.kwargs["reason"], ZIP_NON_CSV)

    @patch("datasets.tasks.submit_new_upload")
    @patch("datasets.tasks._move_to_canonical_path", return_value="user_alice/my-data/data.zip")
    @patch("datasets.tasks.Dataset.objects.create")
    @patch("datasets.tasks._send_notification_email")
    @patch("datasets.tasks.delete_dataset_objects")
    @patch("datasets.tasks.check_uploaded_file", return_value=None)
    @patch("datasets.tasks.object_exists", return_value=True)
    def test_accepted_file_becomes_a_dataset(
        self, _exists, _check, mock_delete, mock_email, mock_create, _move, mock_submit
    ):
        finalize_dataset_upload(**self.KWARGS)

        mock_delete.assert_not_called()
        mock_create.assert_called_once()
        self.assertEqual(mock_create.call_args.kwargs["data_file"], "user_alice/my-data/data.zip")
        self.assertTrue(mock_email.call_args.kwargs["success"])
        mock_submit.assert_called_once()


class _FakeS3:
    """Just enough of a boto3 S3 client for check_uploaded_file: HEAD and ranged GET."""

    def __init__(self, data: bytes = b"", error: Exception | None = None):
        self.data = data
        self.error = error

    def head_object(self, Bucket, Key):
        if self.error:
            raise self.error
        return {"ContentLength": len(self.data)}

    def get_object(self, Bucket, Key, Range):
        if self.error:
            raise self.error
        start, end = (int(x) for x in Range.removeprefix("bytes=").split("-"))
        return {"Body": io.BytesIO(self.data[start:end + 1])}


def _zip_bytes(names) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in names:
            zf.writestr(name, "a,b\n1,2\n")
    return buf.getvalue()


class CheckUploadedFileTests(SimpleTestCase):
    def _check(self, key, client):
        return check_uploaded_file(bucket_name="datasets", object_key=key, client=client)

    def test_zip_of_csv_files_is_accepted(self):
        data = _zip_bytes(["a.csv", "sub/b.csv", "__MACOSX/._a.csv"])
        self.assertIsNone(self._check("pending/u/x/data.zip", _FakeS3(data)))

    def test_zip_with_other_files_is_refused(self):
        data = _zip_bytes(["a.csv", "notes.txt"])
        self.assertEqual(self._check("pending/u/x/data.zip", _FakeS3(data)), ZIP_NON_CSV)

    def test_zip_without_csv_is_refused(self):
        self.assertEqual(self._check("pending/u/x/data.zip", _FakeS3(_zip_bytes([]))), ZIP_NO_CSV)

    def test_zip_that_is_not_a_zip_is_refused(self):
        self.assertEqual(self._check("pending/u/x/data.zip", _FakeS3(b"a,b\n1,2\n")), ZIP_INVALID)

    def test_corrupt_zip_is_refused(self):
        data = _zip_bytes(["a.csv"])[:40]  # keeps the signature, loses the central directory
        self.assertEqual(self._check("pending/u/x/data.zip", _FakeS3(data)), ZIP_INVALID)

    def test_plain_csv_is_accepted(self):
        self.assertIsNone(self._check("pending/u/x/data.csv", _FakeS3(b"a,b\n1,2\n")))

    def test_csv_whose_header_starts_with_pk_is_accepted(self):
        self.assertIsNone(self._check("pending/u/x/data.csv", _FakeS3(b"PK_id,value\n1,2\n")))

    def test_zip_renamed_to_csv_is_refused(self):
        data = _zip_bytes(["a.csv", "photo.png"])
        self.assertEqual(self._check("pending/u/x/data.csv", _FakeS3(data)), CSV_IS_ZIP)

    def test_storage_error_lets_the_file_through(self):
        client = _FakeS3(error=ConnectionError("minio down"))
        with self.assertLogs("datasets.services.zip_archive", level="ERROR"):
            self.assertIsNone(self._check("pending/u/x/data.zip", client))


class MetadataTableTests(SimpleTestCase):
    def test_two_item_features_keep_their_columns(self):
        table = metadata_table({"distance": ["m", "distance between 2 points"]})
        self.assertEqual(
            table["rows"],
            [{"name": "distance", "unit": "m", "description": "distance between 2 points",
              "data_type": "", "valid_range": ""}],
        )
        self.assertFalse(table["has_data_type"])
        self.assertFalse(table["has_valid_range"])

    def test_optional_type_and_range_are_read(self):
        table = metadata_table({
            "frequency": ["Hz", "Grid frequency", "float", "49.5 – 50.5"],
            "sensor_id": ["", "Sensor identifier", "string"],
        })
        self.assertEqual(table["rows"][0]["valid_range"], "49.5 – 50.5")
        self.assertEqual(table["rows"][1]["data_type"], "string")
        self.assertEqual(table["rows"][1]["valid_range"], "")
        self.assertTrue(table["has_data_type"])
        self.assertTrue(table["has_valid_range"])

    def test_pilot_partner_is_not_a_feature(self):
        table = metadata_table({"pilot_partner": "RDN", "frequency": ["Hz", "Grid frequency"]})
        self.assertEqual([row["name"] for row in table["rows"]], ["frequency"])

    def test_missing_metadata_gives_no_rows(self):
        self.assertEqual(metadata_table(None)["rows"], [])

    def test_rows_are_sorted_by_name_not_jsonb_key_length(self):
        table = metadata_table({"ED09": ["W", "a"], "BOMBAS": ["W", "b"], "LEVI": ["-", "c"]})
        self.assertEqual([row["name"] for row in table["rows"]], ["BOMBAS", "ED09", "LEVI"])

    def test_entry_that_is_not_a_list_is_shown_not_dropped(self):
        table = metadata_table({"frequency": "Hz", "flow": {"unit": "l/s"}})
        rows = {row["name"]: row for row in table["rows"]}
        self.assertEqual(rows["frequency"]["description"], "Hz")
        self.assertEqual(rows["flow"]["description"], '{"unit": "l/s"}')

    def test_nested_cells_are_json_not_python_repr(self):
        table = metadata_table({"power": ["kW", "Active power", "float", [0, 100]]})
        self.assertEqual(table["rows"][0]["valid_range"], "[0, 100]")


class MetadataTableRenderTests(TestCase):
    """The details page draws the optional columns only when a feature fills them."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="meta@example.com", password="pw-for-tests")

    def _render(self, metadata):
        dataset = Dataset.objects.create(
            name="meta-test", publisher=self.user, visibility=False,
            status=Dataset.Status.APPROVED, size_gb=Decimal("1.00"),
            data_file="user_x/meta-test/data.csv", bucket_name="energyguard-datasets",
            metadata=metadata,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dataset_details", args=[dataset.pk]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_unit_and_description_only_keeps_three_columns(self):
        html = self._render({"distance": ["m", "distance between 2 points"]})
        self.assertIn("distance between 2 points", html)
        self.assertNotIn("Data Type</th>", html)
        self.assertNotIn("Valid Range</th>", html)

    def test_type_and_range_add_their_columns(self):
        html = self._render({"frequency": ["Hz", "Grid frequency", "float", "49.5 – 50.5"]})
        self.assertIn("Data Type</th>", html)
        self.assertIn("Valid Range</th>", html)
        self.assertIn("49.5 – 50.5", html)

    def test_pilot_partner_only_shows_the_empty_state(self):
        html = self._render({"pilot_partner": "BER"})
        self.assertIn("No feature metadata has been provided", html)
        self.assertNotIn(">pilot_partner<", html)
