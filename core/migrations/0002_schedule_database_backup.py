import datetime

from django.db import migrations
from django.utils import timezone

SCHEDULE_FUNC = "core.tasks.backup_database"

# django_q's Schedule.DAILY, hard-coded for the reason given in
# digitaltwins/migrations/0004_schedule_reconcile_stale_rdn_jobs.py.
DAILY = "D"


def create_schedule(apps, schema_editor):
    # apps.get_model, not the live django_q model - see digitaltwins 0004.
    Schedule = apps.get_model("django_q", "Schedule")

    # Every night at 02:00 UTC, before the 03:00 clean-ups
    now = timezone.now()
    next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += datetime.timedelta(days=1)

    Schedule.objects.update_or_create(
        func=SCHEDULE_FUNC,
        defaults={"name": "Back up the database", "schedule_type": DAILY, "next_run": next_run},
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func=SCHEDULE_FUNC).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_schedule_housekeeping"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
