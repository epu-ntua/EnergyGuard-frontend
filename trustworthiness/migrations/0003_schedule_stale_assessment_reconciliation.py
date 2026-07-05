from django.db import migrations

SCHEDULE_FUNC = "trustworthiness.tasks.reconcile_stale_assessments"


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.update_or_create(
        func=SCHEDULE_FUNC,
        defaults={
            "name": "Reconcile stale running assessments",
            "schedule_type": Schedule.HOURLY,
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(func=SCHEDULE_FUNC).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("trustworthiness", "0002_assessment_error_message_assessment_status"),
        ("django_q", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
