import gzip
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from datasets.models import Dataset
from datasets.services.datalake import PARTNER_DATABASES, UnknownPartnerError, resolve_partner
from datasets.services.pilot import PILOT_PARTNERS, pilot_object_key


class PilotPartnerResolutionTests(SimpleTestCase):
    def _dataset(self, *, data_file="", metadata=None):
        return Dataset(name="d", data_file=data_file, metadata=metadata, size_gb=1)

    def test_metadata_declares_partner(self):
        dataset = self._dataset(metadata={"pilot_partner": "rdn"})
        self.assertEqual(dataset.pilot_partner, "RDN")
        self.assertTrue(dataset.is_pilot)

    def test_pilot_key_prefix_declares_partner(self):
        dataset = self._dataset(data_file="pilot_datasets/CEDER/CEDER.csv.gz")
        self.assertEqual(dataset.pilot_partner, "CEDER")

    def test_metadata_wins_over_key_prefix(self):
        dataset = self._dataset(
            data_file="pilot_datasets/CEDER/x.csv.gz", metadata={"pilot_partner": "BER"}
        )
        self.assertEqual(dataset.pilot_partner, "BER")

    def test_pilot_object_key_layout(self):
        self.assertEqual(pilot_object_key("rea"), "pilot_datasets/REA/REA.csv.gz")

    def test_partner_registries_agree(self):
        self.assertEqual(set(PILOT_PARTNERS), set(PARTNER_DATABASES))

    def test_regular_minio_dataset_is_not_pilot(self):
        dataset = self._dataset(data_file="user_theo/my-data/my.csv")
        self.assertIsNone(dataset.pilot_partner)
        self.assertFalse(dataset.is_pilot)

    def test_unknown_partner_is_ignored(self):
        dataset = self._dataset(
            data_file="pilot_datasets/NOPE/x.csv.gz", metadata={"pilot_partner": "NOPE"}
        )
        self.assertIsNone(dataset.pilot_partner)

    def test_resolve_partner_maps_to_database(self):
        self.assertEqual(resolve_partner("rdn"), "TEF1_RDN")
        self.assertEqual(resolve_partner(" ENGREEN "), "TEF7_ENGREEN")
        with self.assertRaises(UnknownPartnerError):
            resolve_partner("BOGUS")


class GzipPreviewTests(SimpleTestCase):
    def _dataset(self, key):
        dataset = Dataset(name="d", size_gb=1, data_file=key, bucket_name="datasets")
        dataset.id = 7
        return dataset

    def _client_returning(self, payload):
        client = MagicMock()

        def get_object(**kwargs):
            rng = kwargs.get("Range", "")
            if rng == "bytes=0-3":
                return {"Body": io.BytesIO(payload[:4])}
            return {"Body": io.BytesIO(payload)}

        client.get_object.side_effect = get_object
        return client

    def test_gzipped_csv_is_inflated_for_preview(self):
        from datasets.views import preview as preview_view

        csv_bytes = b"ts_id,sensor_id\n" + b"".join(
            f"{i},sensor_{i}\n".encode() for i in range(500)
        )
        payload = gzip.compress(csv_bytes)

        dataset = self._dataset("pilot_datasets/REA/REA.csv.gz")
        with patch.object(preview_view, "get_object_or_404", return_value=dataset), \
             patch.object(
                 preview_view, "build_minio_client",
                 return_value=self._client_returning(payload),
             ):
            response = preview_view.dataset_preview.__wrapped__(
                RequestFactory().get("/"), 7
            )

        body = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["headers"], ["ts_id", "sensor_id"])
        self.assertEqual(body["rows"][0], ["0", "sensor_0"])
        self.assertEqual(len(body["rows"]), preview_view.PREVIEW_MAX_ROWS + 1)

    def test_truncated_gzip_stream_still_previews(self):
        """A Range request cuts the gzip member mid-stream; that must not fail."""
        from datasets.views import preview as preview_view

        csv_bytes = b"a,b\n" + b"".join(f"{i},{i}\n".encode() for i in range(50_000))
        payload = gzip.compress(csv_bytes)[: 64 * 1024]

        dataset = self._dataset("pilot_datasets/REA/REA.csv.gz")
        with patch.object(preview_view, "get_object_or_404", return_value=dataset), \
             patch.object(
                 preview_view, "build_minio_client",
                 return_value=self._client_returning(payload),
             ):
            response = preview_view.dataset_preview.__wrapped__(
                RequestFactory().get("/"), 7
            )

        body = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["headers"], ["a", "b"])
        self.assertTrue(body["rows"])


class GzipDownloadTests(SimpleTestCase):
    def test_gz_download_is_served_as_opaque_bytes(self):
        """
        Never Content-Encoding: gzip — the browser would inflate it and save a
        .csv.gz file containing plain CSV.
        """
        from datasets.views import download as download_view

        dataset = Dataset(
            name="d", size_gb=1,
            data_file="pilot_datasets/REA/REA.csv.gz", bucket_name="datasets",
        )
        dataset.id = 7
        body = SimpleNamespace(read=lambda n: b"")
        with patch.object(download_view, "get_object_or_404", return_value=dataset), \
             patch.object(download_view, "build_minio_client") as mock_minio:
            mock_minio.return_value.get_object.return_value = {
                "Body": body, "ContentType": "binary/octet-stream", "ContentLength": 10,
            }
            response = download_view.dataset_download.__wrapped__(
                RequestFactory().get("/"), 7
            )

        self.assertEqual(response["Content-Type"], "application/gzip")
        self.assertNotIn("Content-Encoding", response)
        self.assertIn("REA.csv.gz", response["Content-Disposition"])


class PilotProvisioningTests(SimpleTestCase):
    def test_run_notifies_dms_with_partner_not_minio_prefix(self):
        from datasets.views import run as run_view

        dataset = Dataset(
            name="RDN Pilot Data", size_gb=1, metadata={"pilot_partner": "RDN"}
        )
        dataset.id = 7
        project = SimpleNamespace(id=3)
        request = RequestFactory().post(
            "/", data=json.dumps({"project_id": 3}), content_type="application/json"
        )
        request.user = SimpleNamespace(email="theo@example.com")

        with patch.object(run_view, "get_object_or_404", side_effect=[dataset, project]), \
             patch.object(run_view, "provision_pilot_dataset") as mock_pilot, \
             patch.object(run_view, "provision_user_datasets") as mock_regular, \
             patch.object(Dataset, "projects", create=True), \
             patch.object(run_view.settings, "JUPYTERHUB_URL", "https://hub.example.com"):
            response = run_view.dataset_run.__wrapped__.__wrapped__(request, 7)

        mock_pilot.assert_called_once_with(
            "theo@example.com", "RDN", "RDN Pilot Data"
        )
        mock_regular.assert_not_called()
        self.assertEqual(response.status_code, 200)


class MissingObjectTests(SimpleTestCase):
    """A Dataset row can outlive its object (pilot export not run yet)."""

    def _dataset(self):
        ds = Dataset(
            name="RDN Pilot Data", size_gb=1,
            data_file="pilot_datasets/RDN/RDN.csv.gz", bucket_name="datasets",
        )
        ds.id = 7
        return ds

    def _no_such_key(self):
        from botocore.exceptions import ClientError

        return ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."}},
            "GetObject",
        )

    def test_preview_returns_404_not_500(self):
        from datasets.views import preview as preview_view

        client = MagicMock()
        client.get_object.side_effect = self._no_such_key()
        with patch.object(preview_view, "get_object_or_404", return_value=self._dataset()), \
             patch.object(preview_view, "build_minio_client", return_value=client):
            response = preview_view.dataset_preview.__wrapped__(
                RequestFactory().get("/"), 7
            )

        self.assertEqual(response.status_code, 404)
        body = json.loads(response.content)
        self.assertEqual(body["error"], "This dataset is not available yet.")
        self.assertNotIn("NoSuchKey", body["error"])

    def test_download_raises_404_not_500(self):
        from django.http import Http404

        from datasets.views import download as download_view

        client = MagicMock()
        client.get_object.side_effect = self._no_such_key()
        with patch.object(download_view, "get_object_or_404", return_value=self._dataset()), \
             patch.object(download_view, "build_minio_client", return_value=client):
            with self.assertRaises(Http404):
                download_view.dataset_download.__wrapped__(RequestFactory().get("/"), 7)

    def test_other_storage_errors_still_500(self):
        from botocore.exceptions import ClientError

        from datasets.views import preview as preview_view

        client = MagicMock()
        client.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetObject"
        )
        with patch.object(preview_view, "get_object_or_404", return_value=self._dataset()), \
             patch.object(preview_view, "build_minio_client", return_value=client):
            response = preview_view.dataset_preview.__wrapped__(
                RequestFactory().get("/"), 7
            )

        self.assertEqual(response.status_code, 500)


class SeedSizeTests(SimpleTestCase):
    def test_size_gb_conversion_and_floor(self):
        from datasets.management.commands.seed_pilot_datasets import _size_gb

        self.assertEqual(str(_size_gb(724497048)), "0.67")   # CEDER ~691 MB
        self.assertEqual(str(_size_gb(5645874)), "0.01")     # REA 5.4 MB -> floor
        self.assertEqual(str(_size_gb(None)), "0.01")        # not exported
        self.assertEqual(str(_size_gb(0)), "0.01")
