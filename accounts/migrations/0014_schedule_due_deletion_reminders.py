import datetime

from django.db import migrations
from django.utils import timezone

SCHEDULE_FUNC = "accounts.tasks.remind_admins_of_due_deletions"

# django_q's Schedule.DAILY, hard-coded for the reason given in
# digitaltwins/migrations/0004_schedule_reconcile_stale_rdn_jobs.py.
DAILY = "D"


def create_schedule(apps, schema_editor):
    # apps.get_model, not the live django_q model - see digitaltwins 0004.
    Schedule = apps.get_model("django_q", "Schedule")

    # Every morning at 07:00 UTC (09:00 or 10:00 in Athens)
    now = timezone.now()
    next_run = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += datetime.timedelta(days=1)

    Schedule.objects.update_or_create(
        func=SCHEDULE_FUNC,
        defaults={
            "name": "Remind admins of account deletions due today",
            "schedule_type": DAILY,
            "next_run": next_run,
        },
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func=SCHEDULE_FUNC).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_privacyrequest"),
        # Latest, not 0001_initial: the update_or_create uses Schedule.name,
        # added by a later django_q migration.
        ("django_q", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
