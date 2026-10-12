"""Old dotted paths of the digitaltwins background tasks.

The tasks live with their twin now (digitaltwins/rdn/tasks.py, digitaltwins/ber/tasks.py).
django_q stores a task's dotted path in the database - with each queued task and in
Schedule rows, including the self-rescheduling RDN poll chain - so rows written
under these old paths before a deploy must still resolve. Migration 0011 moves the
Schedule rows to the new paths; this module covers anything already queued.
Safe to delete once no django_q OrmQ/Schedule row references 'digitaltwins.tasks.'.
"""

from .ber.tasks import (  # noqa: F401
    notify_ber_request_decision,
    notify_ber_results_updated,
    send_ber_cancellation_email,
    send_ber_notification_email,
    warm_ber_results_cache,
)
from .rdn.tasks import poll_rdn_job, reconcile_stale_rdn_jobs  # noqa: F401
