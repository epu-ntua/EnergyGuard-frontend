import logging
from datetime import timedelta

from django.utils import timezone

from .models import RdnSimulationJob
from .services import RdnApiError, get_rdn_job_status, download_rdn_result

logger = logging.getLogger(__name__)

_RDN_JOB_MAX_WAIT = timedelta(hours=1)  # judgment call: our one real run exceeded 14 min with no RDN-documented ceiling
_RDN_JOB_POLL_INTERVAL_SECONDS = 15

STALE_RUNNING_THRESHOLD = timedelta(hours=2)


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
                status=RdnSimulationJob.Status.FAILED, error_message=str(exc),
            )
            return
        RdnSimulationJob.objects.filter(pk=job_id).update(status=RdnSimulationJob.Status.COMPLETED, result=result)
        return

    if rdn_status == 'failed':
        RdnSimulationJob.objects.filter(pk=job_id).update(
            status=RdnSimulationJob.Status.FAILED,
            error_message=status_payload.get('errorMessage') or 'RDN reported the job as failed.',
        )
        return

    if timezone.now() - job.created_at > _RDN_JOB_MAX_WAIT:
        RdnSimulationJob.objects.filter(pk=job_id).update(
            status=RdnSimulationJob.Status.FAILED,
            error_message=f'Timed out after {_RDN_JOB_MAX_WAIT} waiting for RDN.',
        )
        return

    _reschedule_poll(job_id)  # still pending/running on RDN's side


def _reschedule_poll(job_id):
    from django_q.tasks import schedule
    from django_q.models import Schedule

    schedule(
        'digitaltwins.tasks.poll_rdn_job', job_id,
        schedule_type=Schedule.ONCE,
        next_run=timezone.now() + timedelta(seconds=_RDN_JOB_POLL_INTERVAL_SECONDS),
    )  # repeats left at its default (-1) so this row self-deletes once it fires


def reconcile_stale_rdn_jobs():
    """Backstop for a broken reschedule chain (e.g. a bug that returns before calling
    _reschedule_poll) - not the primary safety net, since polling itself survives
    qcluster/web restarts via persisted Schedule rows."""
    cutoff = timezone.now() - STALE_RUNNING_THRESHOLD
    count = RdnSimulationJob.objects.filter(
        status__in=[RdnSimulationJob.Status.PENDING, RdnSimulationJob.Status.RUNNING],
        created_at__lt=cutoff,
    ).update(
        status=RdnSimulationJob.Status.FAILED,
        error_message='Job lost - no result was ever recorded.',
    )
    if count:
        logger.warning('Reconciled %s stale RDN job(s)', count)
    return count
