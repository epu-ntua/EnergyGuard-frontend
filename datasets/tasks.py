import logging
import os
import shutil
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse

from .models import Dataset
from .services import MinioUploadError, delete_dataset_objects, upload_dataset_objects

logger = logging.getLogger(__name__)


class _FileFromPath:
    """Minimal file-like wrapper so upload_dataset_objects can work with saved paths."""

    def __init__(self, path: str, name: str, content_type: str):
        self.path = path
        self.name = name
        self.content_type = content_type
        self._fh = None

    def _ensure_open(self):
        if self._fh is None or self._fh.closed:
            self._fh = open(self.path, "rb")

    def seek(self, pos):
        self._ensure_open()
        self._fh.seek(pos)

    def read(self, size=-1):
        self._ensure_open()
        return self._fh.read(size)

    def close(self):
        if self._fh and not self._fh.closed:
            self._fh.close()


def process_dataset_upload(
    *,
    tmp_dir: str,
    data_file_name: str,
    data_file_content_type: str,
    metadata_file_name: str | None,
    metadata_file_content_type: str | None,
    metadata_json: dict | None,
    dataset_name: str,
    dataset_label: str,
    dataset_visibility: bool,
    dataset_description: str,
    size_gb: str,
    user_id: int,
    user_username: str,
    user_email: str,
    user_display_name: str,
    site_url: str,
):
    """
    Async task: uploads dataset files to MinIO, saves the Dataset record,
    and sends a confirmation email to the user.
    """
    data_file = None
    metadata_file = None

    try:
        data_file_path = os.path.join(tmp_dir, data_file_name)
        data_file = _FileFromPath(data_file_path, data_file_name, data_file_content_type)

        if metadata_file_name:
            metadata_file_path = os.path.join(tmp_dir, metadata_file_name)
            metadata_file = _FileFromPath(
                metadata_file_path, metadata_file_name, metadata_file_content_type or "application/json"
            )

        try:
            upload_result = upload_dataset_objects(
                user_name=user_username,
                dataset_name=dataset_name,
                data_file=data_file,
                metadata_file=metadata_file,
                metadata_json=metadata_json,
            )
        except MinioUploadError:
            logger.exception(
                "Async dataset upload to MinIO failed for user '%s', dataset '%s'.",
                user_username,
                dataset_name,
            )
            _send_notification_email(
                user_email=user_email,
                user_display_name=user_display_name,
                dataset_name=dataset_name,
                success=False,
                site_url=site_url,
            )
            return

        try:
            with transaction.atomic():
                Dataset.objects.create(
                    name=dataset_name,
                    data_file=upload_result["data_file_key"],
                    metadata_file=upload_result["metadata_file_key"],
                    bucket_name=upload_result["bucket_name"],
                    label=dataset_label,
                    source=Dataset.Source.OWN_DS,
                    status=Dataset.Status.UNDER_REVIEW,
                    visibility=dataset_visibility,
                    size_gb=Decimal(size_gb),
                    publisher_id=user_id,
                    description=dataset_description,
                    metadata=metadata_json,
                )
        except Exception:
            logger.exception(
                "Async DB save failed for user '%s', dataset '%s'. Rolling back MinIO objects.",
                user_username,
                dataset_name,
            )
            try:
                delete_dataset_objects(
                    bucket_name=upload_result["bucket_name"],
                    data_file_key=upload_result["data_file_key"],
                    metadata_file_key=upload_result["metadata_file_key"],
                )
            except MinioUploadError:
                logger.exception(
                    "Failed to rollback MinIO objects after async DB save failure. "
                    "bucket='%s', data_key='%s'",
                    upload_result.get("bucket_name", ""),
                    upload_result.get("data_file_key", ""),
                )
            _send_notification_email(
                user_email=user_email,
                user_display_name=user_display_name,
                dataset_name=dataset_name,
                success=False,
                site_url=site_url,
            )
            return

        _send_notification_email(
            user_email=user_email,
            user_display_name=user_display_name,
            dataset_name=dataset_name,
            success=True,
            site_url=site_url,
        )

    finally:
        if data_file:
            data_file.close()
        if metadata_file:
            metadata_file.close()
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            logger.warning("Failed to clean up tmp upload dir '%s'.", tmp_dir)


def _send_notification_email(
    *,
    user_email: str,
    user_display_name: str,
    dataset_name: str,
    success: bool,
    site_url: str,
):
    if not user_email:
        return

    datasets_path = reverse("datasets_list") + "?tab=my"
    upload_path = reverse("dataset_upload")

    if success:
        subject = "Your dataset has been uploaded — EnergyGuard"
        message = (
            f"Hi {user_display_name},\n\n"
            f"Your dataset \"{dataset_name}\" has been successfully uploaded to EnergyGuard "
            f"and is now under review.\n\n"
            f"You can view your datasets here:\n{site_url.rstrip('/')}{datasets_path}\n\n"
            f"Best regards,\nThe EnergyGuard Team"
        )
    else:
        subject = "Dataset upload failed — EnergyGuard"
        message = (
            f"Hi {user_display_name},\n\n"
            f"Unfortunately, your dataset \"{dataset_name}\" could not be uploaded to EnergyGuard "
            f"due to an error.\n\n"
            f"Please try again:\n{site_url.rstrip('/')}{upload_path}\n\n"
            f"If the problem persists, contact our support team.\n\n"
            f"Best regards,\nThe EnergyGuard Team"
        )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
        )
    except Exception:
        logger.exception(
            "Failed to send dataset upload notification email to '%s' for dataset '%s'.",
            user_email,
            dataset_name,
        )
