"""The background jobs of code analysis and robustness, recorded on their Assessment.

Each job runs in a thread of the web process that started it, and its
Assessment is its only record: status, results and error. Any gunicorn worker
can then answer for any job, but a restart still kills the running threads,
which fail_interrupted_jobs records as soon as the web container starts again.
"""

import logging

from django.db import connection

from .models import Assessment

logger = logging.getLogger(__name__)

# The types whose jobs run in web threads (the AI Act questionnaire runs none)
THREAD_JOB_TYPES = (Assessment.AssessmentType.CODE_ANALYSIS, Assessment.AssessmentType.ROBUSTNESS)

INTERRUPTED_MESSAGE = "Interrupted by a server restart. Please run the assessment again."


def record_job_outcome(assessment_id, *, results=None, error_message=None, input_data=None):
    """Record a finished job on its Assessment: failed when `error_message` is
    given, else completed with `results`. `input_data` keys are merged into the
    Assessment's.

    Results that cannot be saved are recorded as a failure instead, so the job
    never stays on 'running' while its user polls it. If even that fails (the
    database is down), reconcile_stale_assessments fails it within hours.
    """
    failed = error_message is not None
    try:
        assessment = Assessment.objects.get(id=assessment_id)
        assessment.status = Assessment.Status.FAILED if failed else Assessment.Status.COMPLETED
        assessment.results = None if failed else results
        assessment.error_message = error_message
        if input_data:
            assessment.input_data = {**(assessment.input_data or {}), **input_data}
        assessment.save(update_fields=["status", "results", "error_message", "input_data"])
        return
    except Exception:
        logger.exception("Failed to record the outcome of assessment_id=%s", assessment_id)
    if failed:
        return
    try:
        Assessment.objects.filter(id=assessment_id).update(
            status=Assessment.Status.FAILED, error_message="The results could not be saved. Please run the assessment again.",
        )
    except Exception:
        logger.exception("Failed to mark assessment_id=%s as failed", assessment_id)


def release_thread_connection():
    """Close the job thread's database connection: with CONN_MAX_AGE, only
    request threads have theirs closed for them. Skipped inside a transaction,
    which is how the tests run a job in their own thread."""
    if not connection.in_atomic_block:
        connection.close()


def fail_interrupted_jobs():
    """Fail every job still 'running'. Only safe while no web process runs:
    the web container's start command calls it (fail_interrupted_assessments)
    before the server, when every job thread of the last run is gone."""
    count = Assessment.objects.filter(
        assessment_type__in=THREAD_JOB_TYPES, status=Assessment.Status.RUNNING,
    ).update(status=Assessment.Status.FAILED, error_message=INTERRUPTED_MESSAGE)
    if count:
        logger.warning("Failed %s assessment job(s) interrupted by a restart", count)
    return count
