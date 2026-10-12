"""RDN background tasks, run by the qcluster worker."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django_q.tasks import async_task

from digitaltwins.models import RdnSimulationJob

from .services.client import RdnApiError, download_rdn_result, get_rdn_job_status
from .services.results import store_result

logger = logging.getLogger(__name__)

_RDN_JOB_POLL_INTERVAL_SECONDS = 15

STALE_RUNNING_THRESHOLD = timedelta(days=7)
# A job is pending only between its creation and the start of polling, a matter of
# seconds; one still pending after this long had its first poll fail to queue.
ORPHANED_PENDING_THRESHOLD = timedelta(minutes=10)


def start_polling(job):
    """pending -> running, with the first status check queued in the same transaction.

    Q_CLUSTER uses the ORM broker on the default database, so the status change and
    the queued poll commit together or not at all: a job is never "running" with
    nothing polling it. Returns False if the job was no longer pending.
    """
    with transaction.atomic():
        started = RdnSimulationJob.objects.filter(
            pk=job.pk, status=RdnSimulationJob.Status.PENDING,
        ).update(status=RdnSimulationJob.Status.RUNNING)
        if started:
            async_task('digitaltwins.rdn.tasks.poll_rdn_job', job.pk)
    return bool(started)


def poll_rdn_job(job_id):
    """Check an RDN job once and either finish it or schedule the next check.

    Runs in the qcluster worker process, not the web process, and each invocation
    is a single short HTTP call - long waits happen across many small, independently
    persisted steps (see _reschedule_poll) rather than inside one long-lived task.
    """
    job = RdnSimulationJob.objects.filter(pk=job_id).first()
    if job is None or job.status not in (RdnSimulationJob.Status.PENDING, RdnSimulationJob.Status.RUNNING):
        return  # already terminal (or reconciled away) - nothing to do

    try:
        status_payload = get_rdn_job_status(job.rdn_request_id)
    except RdnApiError:
        logger.exception('RDN status poll failed for request %s, will retry', job.rdn_request_id)
        _reschedule_poll(job_id)
        return

    rdn_status = status_payload.get('status')

    if rdn_status == 'completed':
        try:
            result = download_rdn_result(job.rdn_request_id)
        except RdnApiError as exc:
            logger.exception('Failed to download RDN result for request %s', job.rdn_request_id)
            RdnSimulationJob.objects.filter(pk=job_id).update(
                status=RdnSimulationJob.Status.FAILED, error_message=str(exc), updated_at=timezone.now(),
            )
            return
        # Straight to object storage. Only if that fails does the payload land in
        # the JSONB column, so an hour-long run is never lost to a storage blip.
        result_key = store_result(job.rdn_request_id, result)
        RdnSimulationJob.objects.filter(pk=job_id).update(
            status=RdnSimulationJob.Status.COMPLETED,
            result_key=result_key or '',
            result=None if result_key else result,
            updated_at=timezone.now(),
        )
        return

    if rdn_status == 'failed':
        RdnSimulationJob.objects.filter(pk=job_id).update(
            status=RdnSimulationJob.Status.FAILED,
            error_message=status_payload.get('errorMessage') or 'RDN reported the job as failed.',
            updated_at=timezone.now(),
        )
        return

    _reschedule_poll(job_id)  # still pending/running on RDN's side - RDN confirmed this can
    # legitimately last a long time (e.g. their DT worker being temporarily unavailable),
    # so we keep polling indefinitely rather than giving up on our own schedule.


def _reschedule_poll(job_id):
    from django_q.tasks import schedule
    from django_q.models import Schedule

    schedule(
        'digitaltwins.rdn.tasks.poll_rdn_job', job_id,
        schedule_type=Schedule.ONCE,
        next_run=timezone.now() + timedelta(seconds=_RDN_JOB_POLL_INTERVAL_SECONDS),
    )  # repeats left at its default (-1) so this row self-deletes once it fires


def reconcile_stale_rdn_jobs():
    """Hourly backstop for the poll chain - not the primary safety net, since polling
    itself survives qcluster/web restarts via persisted Schedule rows.

    - Starts polling jobs left pending after their input reached RDN, because the
      first poll couldn't be queued (see rdn_grid_simulate).
    - Fails jobs with no result after a week (e.g. a bug that returns before calling
      _reschedule_poll, or a job RDN never knew about).

    Returns the number of jobs failed.
    """
    cutoff = timezone.now() - STALE_RUNNING_THRESHOLD

    orphaned = RdnSimulationJob.objects.filter(
        status=RdnSimulationJob.Status.PENDING,
        created_at__lt=timezone.now() - ORPHANED_PENDING_THRESHOLD,
        created_at__gte=cutoff,
    )
    restarted = sum(start_polling(job) for job in orphaned)
    if restarted:
        logger.warning('Started polling %s RDN job(s) left pending', restarted)

    count = RdnSimulationJob.objects.filter(
        status__in=[RdnSimulationJob.Status.PENDING, RdnSimulationJob.Status.RUNNING],
        created_at__lt=cutoff,
    ).update(
        status=RdnSimulationJob.Status.FAILED,
        error_message='Job lost - no result was ever recorded.',
        updated_at=timezone.now(),
    )
    if count:
        logger.warning('Reconciled %s stale RDN job(s)', count)
    return count
