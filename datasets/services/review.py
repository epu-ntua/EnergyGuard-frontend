"""Publication review of user datasets.

A publisher who makes a dataset public submits it for review; it reaches the
"Public" catalogue only after a reviewer (permission `datasets.review_dataset`)
approves it. Private datasets are never reviewed. Editing an approved dataset
sends it back to review; a rejected dataset stays rejected.

Status changes go through here so the conditional UPDATEs (a decision and an
edit racing each other cannot both win) and the notifications live in one
place. Notifications are enqueued inside the same transaction as the change:
Q_CLUSTER uses the ORM broker on the default database, so the task row commits
or rolls back with it (same reasoning as digitaltwins.ber.services.requests).
"""

import logging
from enum import StrEnum

from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_q.tasks import async_task

from ..models import Dataset

logger = logging.getLogger(__name__)

Status = Dataset.Status

REJECTION_REASON_MAX_LENGTH = 2000


class ReviewError(Exception):
    """The decision isn't allowed or didn't happen. str() is the message for the user."""


class EditOutcome(StrEnum):
    """What saving the edit form meant for the dataset's review (see apply_edit)."""
    NONE = 'none'
    SUBMITTED = 'submitted'   # newly made public: first review
    REOPENED = 'reopened'     # approved dataset changed: reviewed again
    REJECTED = 'rejected'     # public but rejected: stays out of the catalogue


def _notify_submitted(dataset_id):
    async_task('datasets.tasks.notify_dataset_submitted', dataset_id)


def submit_new_upload(dataset):
    """Called once the upload task created the dataset: a public upload goes
    straight to review."""
    if dataset.is_awaiting_review:
        Dataset.objects.filter(pk=dataset.pk).update(submitted_at=timezone.now())
        _notify_submitted(dataset.pk)


def apply_edit(form, *, was_awaiting_review):
    """Save the publisher's edit form and work out what it means for review.

    Only the form's own fields are written: a full save would put back the
    status loaded with the form and could undo a reviewer's decision taken in
    the meantime. The status changes are conditional UPDATEs in the same
    transaction, so an edited approved dataset is never public unreviewed.
    """
    with transaction.atomic():
        dataset = form.save(commit=False)
        dataset.save(update_fields=[*form.Meta.fields, 'updated_at'])
        now = timezone.now()
        published = Dataset.objects.filter(
            pk=dataset.pk, visibility=True, publisher__isnull=False, status=Status.APPROVED,
        )
        # Any change to an approved public dataset (or making an approved one
        # public again) needs a fresh approval. Saving without changes does not.
        if form.has_changed() and published.update(
            status=Status.UNDER_REVIEW, submitted_at=now,
            rejection_reason='', reviewed_by=None, reviewed_at=None,
        ):
            outcome = EditOutcome.REOPENED
        elif not was_awaiting_review and Dataset.objects.awaiting_review().filter(pk=dataset.pk).update(submitted_at=now):
            outcome = EditOutcome.SUBMITTED
        else:
            outcome = EditOutcome.NONE
        if outcome != EditOutcome.NONE:
            _notify_submitted(dataset.pk)

    dataset.refresh_from_db()
    if outcome == EditOutcome.NONE and dataset.visibility and dataset.status == Status.REJECTED:
        outcome = EditOutcome.REJECTED
    return outcome


def _not_awaiting_message(dataset):
    if dataset.is_awaiting_review:
        return 'This dataset was changed after you opened it. Please review the current version and decide again.'
    if not dataset.visibility:
        return 'This dataset is no longer public, so it does not need a review.'
    return f'This dataset has already been {dataset.get_status_display().lower()}.'


def _decide(dataset, *, actor, version, status, reason=''):
    """Record the decision, but only on the version the reviewer looked at:
    `version` is the dataset's updated_at as shown on their page. If the
    publisher edited it since, the decision is refused."""
    version = parse_datetime(version or '')
    if version is None:
        raise ReviewError('Please reload the page and decide again.')
    try:
        with transaction.atomic():
            now = timezone.now()
            updated = Dataset.objects.awaiting_review().filter(pk=dataset.pk, updated_at=version).update(
                status=status,
                rejection_reason=reason,
                reviewed_by=actor,
                reviewed_at=now,
                updated_at=now,
            )
            if updated:
                async_task('datasets.tasks.notify_dataset_review_decision', dataset.pk)
    except DatabaseError:
        logger.exception('Could not save the review decision on dataset %s', dataset.pk)
        raise ReviewError('Could not save the decision. Please try again.')

    dataset.refresh_from_db()
    if not updated:
        raise ReviewError(_not_awaiting_message(dataset))


def approve_dataset(dataset, *, actor, version):
    """under_review -> approved; the dataset appears in the public catalogue."""
    _decide(dataset, actor=actor, version=version, status=Status.APPROVED)


def reject_dataset(dataset, *, actor, version, reason):
    """under_review -> rejected, with the reason shown to the publisher."""
    reason = (reason or '').strip()
    if not reason:
        raise ReviewError('A rejection reason is required.')
    if len(reason) > REJECTION_REASON_MAX_LENGTH:
        raise ReviewError(f'The rejection reason can be at most {REJECTION_REASON_MAX_LENGTH} characters.')
    _decide(dataset, actor=actor, version=version, status=Status.REJECTED, reason=reason)
