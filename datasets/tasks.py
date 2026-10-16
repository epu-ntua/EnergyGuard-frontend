import logging
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from core.services.notifications import notify_in_app, platform_link

from .models import Dataset
from .services import MinioUploadError, move_dataset_object, object_exists
from .services.review import submit_new_upload

logger = logging.getLogger(__name__)

# The browser PUTs straight to MinIO, so the object appears some time after the
# wizard finishes. We wait for it - but across many short, independently scheduled
# checks rather than inside one long-lived task, because Q_CLUSTER runs only two
# workers: a task that sleeps for half an hour starves the whole queue (RDN
# polling, notification emails, every other upload) for that entire window.
UPLOAD_POLL_INTERVAL_SECONDS = 15
UPLOAD_MAX_WAIT_SECONDS = 1800


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
    deadline_ts: float | None = None,
):
    """
    Check once whether the uploaded object has landed in MinIO.

    If it has, create the Dataset record as UNDER_REVIEW and notify the user
    (and, for a public dataset, the reviewers).
    If it has not, schedule another check, until `deadline_ts` passes - at which
    point the user is told the upload never completed. The worker is free
    between checks, so a slow upload never blocks the queue.
    """
    if deadline_ts is None:
        deadline_ts = time.time() + UPLOAD_MAX_WAIT_SECONDS

    task_kwargs = {
        "object_key": object_key,
        "bucket_name": bucket_name,
        "user_id": user_id,
        "user_email": user_email,
        "user_display_name": user_display_name,
        "dataset_name": dataset_name,
        "dataset_label": dataset_label,
        "dataset_visibility": dataset_visibility,
        "dataset_description": dataset_description,
        "dataset_size_gb": dataset_size_gb,
        "dataset_metadata": dataset_metadata,
        "site_url": site_url,
        "deadline_ts": deadline_ts,
    }

    try:
        arrived = object_exists(bucket_name=bucket_name, object_key=object_key)
    except MinioUploadError:
        logger.exception("MinIO error while checking object '%s'.", object_key)
        arrived = False

    if not arrived:
        if time.time() < deadline_ts:
            _reschedule_finalize(task_kwargs)
            return
        logger.error(
            "Upload timed out for object '%s'. No Dataset record created.", object_key
        )
        _send_notification_email(
            user_email=user_email,
            user_display_name=user_display_name,
            dataset_name=dataset_name,
            success=False,
            reason="timeout",
            site_url=site_url,
        )
        return

    final_key = _move_to_canonical_path(
        object_key=object_key,
        bucket_name=bucket_name,
        user_id=user_id,
        dataset_name=dataset_name,
    )

    try:
        dataset = Dataset.objects.create(
            name=dataset_name,
            data_file=final_key,
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
    except IntegrityError:
        # Usually a duplicate name, but a NOT NULL or FK violation is one too:
        # only blame the name when it really is taken, or the user goes off
        # renaming a dataset over what is a server-side problem.
        duplicate = Dataset.objects.filter(publisher_id=user_id, name=dataset_name).exists()
        if duplicate:
            logger.warning(
                "Dataset name '%s' already taken; no record created for object '%s'.",
                dataset_name,
                object_key,
            )
        else:
            logger.exception("Failed to create Dataset record for object '%s'.", object_key)
        _send_notification_email(
            user_email=user_email,
            user_display_name=user_display_name,
            dataset_name=dataset_name,
            success=False,
            reason="duplicate_name" if duplicate else "error",
            site_url=site_url,
        )
        return
    except Exception:
        logger.exception("Failed to create Dataset record for object '%s'.", object_key)
        _send_notification_email(
            user_email=user_email,
            user_display_name=user_display_name,
            dataset_name=dataset_name,
            success=False,
            reason="error",
            site_url=site_url,
        )
        return

    _send_notification_email(
        user_email=user_email,
        user_display_name=user_display_name,
        dataset_name=dataset_name,
        success=True,
        site_url=site_url,
        under_review=dataset.is_awaiting_review,
    )
    submit_new_upload(dataset)


def _reschedule_finalize(task_kwargs):
    """Queue the next check as its own ONCE task, freeing the worker in between."""
    from django_q.models import Schedule
    from django_q.tasks import schedule

    schedule(
        "datasets.tasks.finalize_dataset_upload",
        schedule_type=Schedule.ONCE,
        next_run=timezone.now() + timedelta(seconds=UPLOAD_POLL_INTERVAL_SECONDS),
        **task_kwargs,
    )  # repeats defaults to -1, so the row deletes itself once it fires


def _move_to_canonical_path(*, object_key, bucket_name, user_id, dataset_name):
    """Move the object from pending/ to user_<slug>/<dataset>/ so the data
    management server can provision it into JupyterHub.

    Returns the key actually in use - the original pending key if the move
    could not be made.
    """
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error(
            "User %s not found; keeping pending path for dataset '%s'.",
            user_id,
            dataset_name,
        )
        return object_key

    user_slug = slugify(user.username or str(user_id)) or "user"
    dataset_slug = slugify(dataset_name) or "dataset"
    filename = object_key.split("/")[-1]
    dest_key = f"user_{user_slug}/{dataset_slug}/{filename}"
    try:
        move_dataset_object(
            bucket_name=bucket_name, source_key=object_key, dest_key=dest_key
        )
    except MinioUploadError:
        logger.exception(
            "Failed to move dataset object '%s'; keeping pending path.", object_key
        )
        return object_key
    return dest_key


# What actually went wrong, and what the user should do about it. The previous
# single message blamed every failure on an interrupted upload.
FAILURE_REASONS = {
    "timeout": (
        "because the upload was interrupted before it completed",
        "Please try again",
    ),
    "duplicate_name": (
        "because a dataset with that name already exists on the platform",
        "Please upload it again under a different name",
    ),
    "error": (
        "because of an unexpected error while saving it",
        "Please try again",
    ),
}


def _send_notification_email(
    *,
    user_email: str,
    user_display_name: str,
    dataset_name: str,
    success: bool,
    site_url: str,
    reason: str = "timeout",
    under_review: bool = False,
):
    if not user_email:
        return

    datasets_path = reverse("datasets_list") + "?tab=my"
    upload_path = reverse("dataset_upload")

    if success:
        subject = "Your dataset has been uploaded — EnergyGuard"
        review_line = (
            "It is now under review and will appear in the public catalogue once approved.\n\n"
            if under_review else ""
        )
        message = (
            f"Hi {user_display_name},\n\n"
            f'Your dataset "{dataset_name}" has been successfully uploaded to EnergyGuard.\n\n'
            f"{review_line}"
            f"You can view your datasets here:\n{site_url.rstrip('/')}{datasets_path}\n\n"
            f"Best regards,\nThe EnergyGuard Team"
        )
    else:
        cause, next_step = FAILURE_REASONS.get(reason, FAILURE_REASONS["error"])
        subject = "Dataset upload failed — EnergyGuard"
        message = (
            f"Hi {user_display_name},\n\n"
            f'Unfortunately, your dataset "{dataset_name}" could not be uploaded to '
            f"EnergyGuard {cause}.\n\n"
            f"{next_step}:\n{site_url.rstrip('/')}{upload_path}\n\n"
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


# --------------------------- publication review --------------------------- #

def _reviewers():
    """Active users granted `datasets.review_dataset`, directly or through a group.
    Superusers hold every permission implicitly but are not mailed for it: the
    reviewers are whoever the permission was actually given to."""
    permission = Permission.objects.filter(
        content_type__app_label='datasets', codename='review_dataset',
    ).first()
    if permission is None:
        return get_user_model().objects.none()
    return get_user_model().objects.filter(
        Q(user_permissions=permission) | Q(groups__permissions=permission),
        is_active=True,
    ).distinct()


def notify_dataset_submitted(dataset_id):
    """Runs in the qcluster worker - tells reviewers a dataset awaits review."""
    dataset = Dataset.objects.filter(pk=dataset_id).select_related('publisher').first()
    if dataset is None or not dataset.is_awaiting_review:
        return

    reviewers = list(_reviewers())
    if not reviewers:
        logger.warning(
            "Dataset %s awaits review but no user holds 'datasets.review_dataset'; nobody was notified.",
            dataset.pk,
        )
        return

    detail_path = reverse('dataset_details', args=[dataset.pk])
    message = f'Dataset "{dataset.name}" by {dataset.publisher_display} awaits review'
    for reviewer in reviewers:
        notify_in_app(reviewer, message=message, url=detail_path, icon='database')

    recipients = [reviewer.email for reviewer in reviewers if reviewer.email]
    if not recipients:
        return
    try:
        send_mail(
            subject=f'Dataset "{dataset.name}" awaits review — EnergyGuard',
            message=(
                f'A dataset has been submitted for publication on EnergyGuard.\n\n'
                f'Dataset: {dataset.name}\n'
                f'Publisher: {dataset.publisher_display}\n\n'
                f'Review it here:\n{platform_link(detail_path)}\n\n'
                f'All datasets awaiting review:\n{platform_link(reverse("dataset_review_list"))}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
        )
    except Exception:
        logger.exception('Failed to send review request email for dataset %s', dataset.pk)


def notify_dataset_review_decision(dataset_id):
    """Runs in the qcluster worker - tells the publisher their dataset was
    approved or rejected."""
    dataset = Dataset.objects.filter(pk=dataset_id).select_related('publisher').first()
    if dataset is None or dataset.publisher is None:
        return

    if dataset.status == Dataset.Status.APPROVED:
        verb, body_line, icon = 'was approved', 'It is now listed in the public datasets catalogue.', 'circle-check'
    elif dataset.status == Dataset.Status.REJECTED:
        verb, body_line, icon = 'was rejected', f'Reason: {dataset.rejection_reason}', 'circle-xmark'
    else:
        return

    detail_path = reverse('dataset_details', args=[dataset.pk])
    notify_in_app(
        dataset.publisher,
        message=f'Your dataset "{dataset.name}" {verb}',
        url=detail_path,
        icon=icon,
    )

    if not dataset.publisher.email:
        return
    try:
        send_mail(
            subject=f'Your dataset "{dataset.name}" {verb} — EnergyGuard',
            message=(
                f'Hi {dataset.publisher_display},\n\n'
                f'Your dataset "{dataset.name}" {verb}.\n\n'
                f'{body_line}\n\n'
                f'View it here:\n{platform_link(detail_path)}\n\n'
                f'Best regards,\nThe EnergyGuard Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[dataset.publisher.email],
        )
    except Exception:
        logger.exception('Failed to send review decision email for dataset %s', dataset.pk)
