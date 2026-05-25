import logging
import time

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from .models import Dataset
from .services import MinioUploadError, object_exists

logger = logging.getLogger(__name__)


def finalize_dataset_upload(
    *,
    object_key: str,
    bucket_name: str,
    user_id: int,
    user_email: str,
    user_display_name: str,
    dataset_name: str,
    dataset_label: str,
    dataset_visibility: bool,
    dataset_description: str,
    dataset_size_gb,
    dataset_metadata,
    site_url: str,
    max_wait_seconds: int = 1800,
    poll_interval: int = 15,
):
    """
    Polls MinIO until the uploaded file appears, then creates the Dataset record
    as UNDER_REVIEW and notifies the user by email. If the file never arrives
    (e.g. the user closed the tab mid-upload), sends a failure email without
    creating any record.
    """
    elapsed = 0
    while elapsed < max_wait_seconds:
        try:
            if object_exists(bucket_name=bucket_name, object_key=object_key):
                try:
                    Dataset.objects.create(
                        name=dataset_name,
                        data_file=object_key,
                        bucket_name=bucket_name,
                        label=dataset_label,
                        source=Dataset.Source.OWN_DS,
                        status=Dataset.Status.UNDER_REVIEW,
                        visibility=dataset_visibility,
                        size_gb=dataset_size_gb,
                        publisher_id=user_id,
                        description=dataset_description,
                        metadata=dataset_metadata,
                    )
                except Exception:
                    logger.exception(
                        "Failed to create Dataset record for object '%s'.", object_key
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
                return
        except MinioUploadError:
            logger.exception(
                "MinIO error while checking object '%s'.", object_key
            )

        time.sleep(poll_interval)
        elapsed += poll_interval

    logger.error(
        "Upload timed out for object '%s'. No Dataset record created.", object_key
    )
    _send_notification_email(
        user_email=user_email,
        user_display_name=user_display_name,
        dataset_name=dataset_name,
        success=False,
        site_url=site_url,
    )


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
            f"because the upload was interrupted before it completed.\n\n"
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
