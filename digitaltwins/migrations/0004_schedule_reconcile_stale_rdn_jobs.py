from django.db import migrations

SCHEDULE_FUNC = "digitaltwins.tasks.reconcile_stale_rdn_jobs"

# django_q's Schedule.HOURLY. Hard-coded rather than imported: a data migration
# must describe the schema as it was when the migration ran, not as the currently
# installed library happens to define it.
HOURLY = "H"


def create_schedule(apps, schema_editor):
    # apps.get_model, not `from django_q.models import Schedule`. Importing the
    # live model made this migration query columns that only exist after later
    # django_q migrations, so it crashed on any database built from scratch -
    # taking new environments and the whole test suite with it.
    Schedule = apps.get_model("django_q", "Schedule")

    Schedule.objects.update_or_create(
        func=SCHEDULE_FUNC,
        defaults={
            "name": "Reconcile stale RDN simulation jobs",
            "schedule_type": HOURLY,
        },
    )


def remove_schedule(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    Schedule.objects.filter(func=SCHEDULE_FUNC).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("digitaltwins", "0003_rdnsimulationjob"),
        # __latest__, not 0001_initial: the `name` field this migration writes is
        # added by a later django_q migration.
        ("django_q", "__latest__"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
