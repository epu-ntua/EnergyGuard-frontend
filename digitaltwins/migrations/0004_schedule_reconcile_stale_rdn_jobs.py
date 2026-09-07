from django.db import migrations

SCHEDULE_FUNC = "digitaltwins.tasks.reconcile_stale_rdn_jobs"


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.update_or_create(
        func=SCHEDULE_FUNC,
        defaults={
            "name": "Reconcile stale RDN simulation jobs",
            "schedule_type": Schedule.HOURLY,
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(func=SCHEDULE_FUNC).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("digitaltwins", "0003_rdnsimulationjob"),
        ("django_q", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
