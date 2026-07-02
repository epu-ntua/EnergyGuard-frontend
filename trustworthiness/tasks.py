import logging
from datetime import timedelta

from django.utils import timezone

from .models import Assessment

logger = logging.getLogger(__name__)

STALE_RUNNING_THRESHOLD = timedelta(hours=2)


def reconcile_stale_assessments():
    """Mark Assessment rows stuck on 'running' (e.g. lost to a server restart) as failed."""
    cutoff = timezone.now() - STALE_RUNNING_THRESHOLD
    count = Assessment.objects.filter(
        status=Assessment.Status.RUNNING, created_at__lt=cutoff,
    ).update(
        status=Assessment.Status.FAILED,
        error_message="Job lost (server restart or timeout) - no result was ever recorded.",
    )
    if count:
        logger.warning("Reconciled %s stale running assessment(s)", count)
    return count
