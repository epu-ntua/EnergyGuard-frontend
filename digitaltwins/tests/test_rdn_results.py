"""Tests for RDN result storage moving out of the database.

Covers the two things that could go wrong in the move: another user reading a
result, and jobs completed before the move losing access to their payload.
"""

import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from digitaltwins.models import RdnSimulationJob

from .fakes import fake_object_storage

User = get_user_model()


def make_job(user, *, rdn_request_id, status=RdnSimulationJob.Status.COMPLETED, **extra):
    job = RdnSimulationJob.objects.create(
        user=user,
        use_case="VoltageControl",
        grid_section="A",
        assets={"asset_001": "PV"},
        status=status,
        **extra,
    )
    RdnSimulationJob.objects.filter(pk=job.pk).update(rdn_request_id=rdn_request_id)
    job.refresh_from_db()
    return job


class RdnResultEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="rdn-owner@example.com", password="pw")
        cls.other = User.objects.create_user(email="rdn-other@example.com", password="pw")

    def test_legacy_job_still_serves_its_inline_payload(self):
        """Jobs completed before results moved to object storage keep working."""
        payload = {"outputData": [{"InputTimestamp_UTC": "2026-01-01T00:00:00Z"}]}
        job = make_job(self.owner, rdn_request_id=9001, result=payload)

        self.client.force_login(self.owner)
        response = self.client.get(reverse("rdn-grid-result-data", args=[9001]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), payload)
        self.assertEqual(job.result_key, "")

    def test_stored_result_is_streamed_from_object_storage(self):
        payload = {"outputData": [{"InputTimestamp_UTC": "2026-01-01T00:00:00Z"}]}
        raw = json.dumps(payload).encode()
        make_job(
            self.owner,
            rdn_request_id=9002,
            result_key="rdn-grid/9002/result.json",
        )

        class _Body:
            def __init__(self, data):
                self._data = data
                self._sent = False

            def read(self, _n):
                if self._sent:
                    return b""
                self._sent = True
                return self._data

            def close(self):
                pass

        self.client.force_login(self.owner)
        with patch(
            "digitaltwins.rdn.views.open_result_stream", return_value=(_Body(raw), len(raw))
        ):
            response = self.client.get(reverse("rdn-grid-result-data", args=[9002]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(b"".join(response.streaming_content)), payload)

    def test_another_users_result_is_not_readable(self):
        make_job(self.owner, rdn_request_id=9003, result={"outputData": []})

        self.client.force_login(self.other)
        response = self.client.get(reverse("rdn-grid-result-data", args=[9003]))

        self.assertEqual(response.status_code, 404)

    def test_running_job_has_no_result_to_serve(self):
        make_job(self.owner, rdn_request_id=9004, status=RdnSimulationJob.Status.RUNNING)

        self.client.force_login(self.owner)
        response = self.client.get(reverse("rdn-grid-result-data", args=[9004]))

        self.assertEqual(response.status_code, 404)

    def test_status_poll_returns_a_url_not_the_payload(self):
        """The poll runs every 10s; it must not re-serialise the whole result."""
        job = make_job(self.owner, rdn_request_id=9005, result={"outputData": [1, 2, 3]})

        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("rdn-grid-job-status"), {"job": job.pk}
        )

        body = json.loads(response.content)
        self.assertEqual(body["status"], RdnSimulationJob.Status.COMPLETED)
        self.assertNotIn("result", body)
        self.assertEqual(
            body["resultUrl"], reverse("rdn-grid-result-data", args=[9005])
        )


class RdnResultStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="rdn-store@example.com", password="pw")

    def test_completion_writes_to_object_storage_and_clears_the_column(self):
        job = make_job(
            self.owner, rdn_request_id=9100, status=RdnSimulationJob.Status.RUNNING
        )
        payload = {"outputData": []}

        with patch("digitaltwins.rdn.tasks.get_rdn_job_status", return_value={"status": "completed"}), \
             patch("digitaltwins.rdn.tasks.download_rdn_result", return_value=payload), \
             patch("digitaltwins.rdn.tasks.store_result", return_value="rdn-grid/9100/result.json"):
            from digitaltwins.rdn.tasks import poll_rdn_job

            poll_rdn_job(job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, RdnSimulationJob.Status.COMPLETED)
        self.assertEqual(job.result_key, "rdn-grid/9100/result.json")
        self.assertIsNone(job.result)

    def test_storage_failure_falls_back_to_the_database_rather_than_losing_the_run(self):
        job = make_job(
            self.owner, rdn_request_id=9101, status=RdnSimulationJob.Status.RUNNING
        )
        payload = {"outputData": [{"x": 1}]}

        with patch("digitaltwins.rdn.tasks.get_rdn_job_status", return_value={"status": "completed"}), \
             patch("digitaltwins.rdn.tasks.download_rdn_result", return_value=payload), \
             patch("digitaltwins.rdn.tasks.store_result", return_value=None):
            from digitaltwins.rdn.tasks import poll_rdn_job

            poll_rdn_job(job.pk)

        job.refresh_from_db()
        self.assertEqual(job.status, RdnSimulationJob.Status.COMPLETED)
        self.assertEqual(job.result_key, "")
        self.assertEqual(job.result, payload)


class RdnRunDeleteTests(TestCase):
    """A finished run can be deleted with its result; it then can't be continued."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="rdn-deleter@example.com", password="pw")
        cls.other = User.objects.create_user(email="rdn-bystander@example.com", password="pw")

    def setUp(self):
        self.client.force_login(self.owner)
        self.storage = self.enterContext(fake_object_storage())

    def _delete(self, rdn_request_id):
        return self.client.post(reverse("rdn-grid-run-delete", args=[rdn_request_id]))

    def test_completed_run_and_its_result_are_deleted(self):
        key = "rdn-grid/701/result.json"
        self.storage.objects[(settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, key)] = b"{}"
        make_job(self.owner, rdn_request_id=701, result_key=key)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._delete(701)
        self.assertRedirects(response, reverse("rdn-grid-runs"), fetch_redirect_response=False)

        self.assertFalse(RdnSimulationJob.objects.filter(rdn_request_id=701).exists())
        self.assertEqual(self.storage.objects, {})
        self.assertEqual(
            self.client.get(reverse("rdn-grid-follow"), {"requestId": 701}).json(), {"found": False},
        )

    def test_failed_and_legacy_runs_can_be_deleted(self):
        make_job(self.owner, rdn_request_id=702, status=RdnSimulationJob.Status.FAILED)
        make_job(self.owner, rdn_request_id=703, result={"legacy": True})
        self._delete(702)
        self._delete(703)
        self.assertFalse(RdnSimulationJob.objects.filter(rdn_request_id__in=[702, 703]).exists())

    def test_running_or_other_users_runs_are_not_deleted(self):
        make_job(self.owner, rdn_request_id=704, status=RdnSimulationJob.Status.RUNNING)
        make_job(self.other, rdn_request_id=705)

        self.assertEqual(self._delete(704).status_code, 404)
        self.assertEqual(self._delete(705).status_code, 404)
        self.assertEqual(RdnSimulationJob.objects.filter(rdn_request_id__in=[704, 705]).count(), 2)

    def test_result_can_be_downloaded_as_a_file(self):
        make_job(self.owner, rdn_request_id=706, result={"a": 1})
        response = self.client.get(reverse("rdn-grid-result-data", args=[706]), {"download": "1"})
        self.assertIn('attachment; filename="rdn-grid-result-706.json"', response["Content-Disposition"])
