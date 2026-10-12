from django.db import IntegrityError, transaction
from django.utils import timezone
from django_q.tasks import async_task

from ..models import Notification, PrivacyRequest


def submit_privacy_request(request, kind, message=""):
    """
    Records a GDPR request for request.user and notifies the admins.
    Idempotent: if a pending request of the same kind exists it is returned as-is.
    Returns (privacy_request, created).
    """
    user = request.user
    existing = PrivacyRequest.objects.filter(user=user, kind=kind, status=PrivacyRequest.Status.PENDING).first()
    if existing:
        return existing, False

    try:
        with transaction.atomic():
            privacy_request = PrivacyRequest.objects.create(
                user=user, email=user.email, kind=kind, message=message.strip(),
            )
    except IntegrityError:
        # A concurrent submit won the unique_pending_privacy_request race
        return PrivacyRequest.objects.get(user=user, kind=kind, status=PrivacyRequest.Status.PENDING), False

    admin_url = request.build_absolute_uri(f'/admin/accounts/privacyrequest/{privacy_request.pk}/change/')
    transaction.on_commit(lambda: async_task('accounts.tasks.send_privacy_request_emails', privacy_request.pk, admin_url))
    return privacy_request, True


def cancel_privacy_request(user, request_id):
    """Cancels the user's own pending request. Returns True if something was cancelled."""
    updated = PrivacyRequest.objects.filter(
        pk=request_id, user=user, status=PrivacyRequest.Status.PENDING,
    ).update(status=PrivacyRequest.Status.CANCELLED, resolved_at=timezone.now(), updated_at=timezone.now())
    return updated > 0


def resolve_privacy_request(privacy_request, status, resolved_by):
    """Admin side: marks a pending request completed/rejected and tells the user."""
    if not privacy_request.is_pending:
        return False

    privacy_request.status = status
    privacy_request.resolved_at = timezone.now()
    privacy_request.resolved_by = resolved_by
    privacy_request.save(update_fields=['status', 'resolved_at', 'resolved_by', 'updated_at'])

    if privacy_request.user_id:
        Notification.objects.create(
            recipient_id=privacy_request.user_id,
            message=f"Your request for {privacy_request.get_kind_display().lower()} was {privacy_request.get_status_display().lower()}",
            url='/accounts/profile/?tab=privacy',
            icon='shield-alt',
        )
    transaction.on_commit(lambda: async_task('accounts.tasks.send_privacy_request_resolved_email', privacy_request.pk))
    return True
