import datetime

from django.contrib.sessions.models import Session
from django.utils import timezone
from django_q.models import Task

# Task history keeps each task's arguments (emails among them) and, for a
# failure, its traceback. Long enough to debug a failure from the admin.
TASK_HISTORY_DAYS = 30


def clear_expired_sessions():
    """Daily (see core/migrations/0001): Django never deletes expired sessions by
    itself. Same as `manage.py clearsessions` for the database backend. Returns
    the count, which django_q shows as the task's result in the admin."""
    deleted, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
    return deleted


def purge_old_task_results():
    """Daily (see core/migrations/0001): django_q keeps the last 250 successful
    tasks (save_limit) and every failed one, forever. Returns the count, which
    django_q shows as the task's result in the admin."""
    cutoff = timezone.now() - datetime.timedelta(days=TASK_HISTORY_DAYS)
    deleted, _ = Task.objects.filter(stopped__lt=cutoff).delete()
    return deleted
