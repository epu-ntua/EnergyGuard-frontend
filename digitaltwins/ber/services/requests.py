"""State changes of a BER experiment request.

Every change to a request's status or visibility goes through here, so the rules
live in one place: which states allow the change, the conditional UPDATE that
keeps two people acting at once from both succeeding, and which notifications
follow.

Notifications are enqueued inside the same transaction as the change they report.
Q_CLUSTER uses the ORM broker on the default database, so the queued task row
commits or rolls back together with the state change: there is never a decided
request without its notification, nor a notification for a change that didn't
happen. With a non-database broker this would have to become
transaction.on_commit, since the worker could otherwise run before the commit.
"""

import logging
from datetime import datetime, timezone

from django.conf import settings
from django.db import DatabaseError, transaction
from django_q.tasks import async_task

from core.services.object_storage import MinioUploadError
from digitaltwins.models import BerExperimentRequest

from .storage import delete_result_file, store_result_file

logger = logging.getLogger(__name__)

Status = BerExperimentRequest.Status


class TransitionError(Exception):
    """The change isn't allowed or didn't happen. str() is the message for the user."""


def _now():
    return datetime.now(timezone.utc)


def _discard_result_file(object_key, request_id, reason):
    """Best-effort removal of a result file nothing points to any more. A failure
    only leaves an orphaned object, so it is logged (with the key, for manual
    cleanup) rather than surfaced to the staff member."""
    try:
        delete_result_file(object_key)
    except MinioUploadError:
        logger.exception('Could not delete BER result file %s for request %s (%s)', object_key, request_id, reason)


def _store_result_file(experiment_request, result_file, progress_callback):
    try:
        return store_result_file(experiment_request.pk, result_file, progress_callback=progress_callback)
    except MinioUploadError:
        logger.exception('Failed to store BER result file for request %s', experiment_request.pk)
        raise TransitionError('Could not store the result file. Please try again.')


def _not_pending_message(experiment_request):
    if experiment_request.status == Status.CANCELLED:
        return 'The requester cancelled this request.'
    return 'This request has already been decided.'


def ensure_pending(experiment_request):
    """Fail fast before any upload work. complete/reject re-check it atomically."""
    if experiment_request.status != Status.PENDING:
        raise TransitionError(_not_pending_message(experiment_request))


# ── Requester ────────────────────────────────────────────────────────────────

def submit_request(user, experiment_json, *, platform_url):
    """Create a pending request and let BER know (if a BER address is configured)."""
    with transaction.atomic():
        experiment_request = BerExperimentRequest.objects.create(user=user, experiment_json=experiment_json)
        if settings.BER_EMAIL:
            async_task('digitaltwins.ber.tasks.send_ber_notification_email', experiment_request.pk, platform_url)
    return experiment_request


def cancel_request(experiment_request, *, platform_url):
    """pending -> cancelled. Returns False if BER decided it first: the decision stands."""
    now = _now()
    with transaction.atomic():
        cancelled = BerExperimentRequest.objects.filter(
            pk=experiment_request.pk, status=Status.PENDING,
        ).update(status=Status.CANCELLED, cancelled_at=now, updated_at=now)
        if cancelled and settings.BER_EMAIL:
            async_task('digitaltwins.ber.tasks.send_ber_cancellation_email', experiment_request.pk, platform_url)
    return bool(cancelled)


def hide_request(experiment_request):
    """Remove a finished request from its requester's list. BER staff still see it.
    Returns False if it is still pending or already hidden."""
    now = _now()
    return bool(BerExperimentRequest.objects.filter(
        pk=experiment_request.pk, hidden_by_user_at__isnull=True, status__in=BerExperimentRequest.FINISHED_STATUSES,
    ).update(hidden_by_user_at=now, updated_at=now))


# ── BER staff ────────────────────────────────────────────────────────────────

def complete_request(experiment_request, *, actual_start, actual_end, result_file, platform_url,
                     progress_callback=None):
    """pending -> completed with the uploaded result file; notifies the requester."""
    ensure_pending(experiment_request)
    result_key = _store_result_file(experiment_request, result_file, progress_callback)

    try:
        with transaction.atomic():
            # Conditional update: two staff members deciding the same request at
            # once must not both succeed (and both notify the requester).
            updated = BerExperimentRequest.objects.filter(pk=experiment_request.pk, status=Status.PENDING).update(
                actual_start=actual_start, actual_end=actual_end, result_key=result_key,
                status=Status.COMPLETED, updated_at=_now(),
            )
            if updated:
                async_task('digitaltwins.ber.tasks.warm_ber_results_cache', experiment_request.pk)
                async_task('digitaltwins.ber.tasks.notify_ber_request_decision', experiment_request.pk, platform_url)
    except DatabaseError:
        logger.exception('Could not save the completion of BER request %s', experiment_request.pk)
        _discard_result_file(result_key, experiment_request.pk, 'completion was not saved')
        raise TransitionError('Could not save the decision. Please try again.')

    if not updated:
        _discard_result_file(result_key, experiment_request.pk, 'request was decided concurrently')
        experiment_request.refresh_from_db()
        raise TransitionError(_not_pending_message(experiment_request))


def reject_request(experiment_request, *, reason, platform_url):
    """pending -> rejected with the reason shown to the requester; notifies them."""
    ensure_pending(experiment_request)
    with transaction.atomic():
        updated = BerExperimentRequest.objects.filter(pk=experiment_request.pk, status=Status.PENDING).update(
            rejection_reason=reason, status=Status.REJECTED, updated_at=_now(),
        )
        if updated:
            async_task('digitaltwins.ber.tasks.notify_ber_request_decision', experiment_request.pk, platform_url)

    if not updated:
        experiment_request.refresh_from_db()
        raise TransitionError(_not_pending_message(experiment_request))


def replace_result(experiment_request, *, actor, result_file, platform_url, progress_callback=None):
    """Swap a completed request's result file (e.g. the wrong file was uploaded).

    Order matters: the new file goes to a fresh key, the row is switched to it, and
    only then is the old file deleted - so the request always points to a complete
    file. The new key also changes the results cache key, so the requester sees the
    new data immediately.
    """
    if experiment_request.status != Status.COMPLETED:
        raise TransitionError('Only completed requests have a result file to replace.')

    old_key = experiment_request.result_key
    new_key = _store_result_file(experiment_request, result_file, progress_callback)

    try:
        with transaction.atomic():
            # Conditional on the key we read: if another staff member replaced it
            # meanwhile, theirs stands and this upload is discarded.
            switched = BerExperimentRequest.objects.filter(
                pk=experiment_request.pk, status=Status.COMPLETED, result_key=old_key,
            ).update(result_key=new_key, updated_at=_now())
            if switched:
                async_task('digitaltwins.ber.tasks.warm_ber_results_cache', experiment_request.pk)
                async_task('digitaltwins.ber.tasks.notify_ber_results_updated', experiment_request.pk, platform_url)
    except DatabaseError:
        logger.exception('Could not save the new result file of BER request %s', experiment_request.pk)
        _discard_result_file(new_key, experiment_request.pk, 'replacement was not saved')
        raise TransitionError('Could not save the new result file. Please try again.')

    if not switched:
        _discard_result_file(new_key, experiment_request.pk, 'result was replaced concurrently')
        experiment_request.refresh_from_db()
        raise TransitionError('The result file was changed by someone else in the meantime. Check it and try again.')

    if old_key:
        _discard_result_file(old_key, experiment_request.pk, 'replaced by a new upload')
    logger.info('BER request %s result file replaced by user %s', experiment_request.pk, actor.pk)


def archive_request(experiment_request, *, actor):
    """Hide a finished request from the management list. The requester still sees it."""
    now = _now()
    archived = BerExperimentRequest.objects.filter(
        pk=experiment_request.pk, archived_at__isnull=True, status__in=BerExperimentRequest.FINISHED_STATUSES,
    ).update(archived_at=now, archived_by=actor, updated_at=now)

    if not archived:
        experiment_request.refresh_from_db()
        if experiment_request.archived_at:
            raise TransitionError('This request is already archived.')
        raise TransitionError('Pending requests cannot be archived. Reject it first so the requester is informed.')
    logger.info('BER request %s archived by user %s', experiment_request.pk, actor.pk)


def restore_request(experiment_request, *, actor):
    """Bring an archived request back into the management list. False if it wasn't archived."""
    restored = BerExperimentRequest.objects.filter(pk=experiment_request.pk, archived_at__isnull=False).update(
        archived_at=None, archived_by=None, updated_at=_now(),
    )
    if restored:
        logger.info('BER request %s restored from archive by user %s', experiment_request.pk, actor.pk)
    return bool(restored)
