import datetime

from django.db import migrations
from django.utils import timezone

SCHEDULES = {
    "core.tasks.clear_expired_sessions": "Delete expired sessions",
    "core.tasks.purge_old_task_results": "Delete old task results",
}

# django_q's Schedule.DAILY, hard-coded for the reason given in
# digitaltwins/migrations/0004_schedule_reconcile_stale_rdn_jobs.py.
DAILY = "D"


def create_schedules(apps, schema_editor):
    # apps.get_model, not the live django_q model - see digitaltwins 0004.
    Schedule = apps.get_model("django_q", "Schedule")

    # Every night at 03:00 UTC (05:00 or 06:00 in Athens)
    now = timezone.now()
    next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += datetime.timedelta(days=1)

    for func, name in SCHEDULES.items():
        Schedule.objects.update_or_create(
            func=func,
            defaults={"name": name, "schedule_type": DAILY, "next_run": next_run},
        )


def remove_schedules(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func__in=SCHEDULES).delete()


class Migration(migrations.Migration):

    dependencies = [
        # Latest, not 0001_initial: the update_or_create uses Schedule.name,
        # added by a later django_q migration.
        ("django_q", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_schedules, remove_schedules),
    ]
