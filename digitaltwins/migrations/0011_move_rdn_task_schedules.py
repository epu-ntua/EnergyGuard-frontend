from django.db import migrations

# django_q Schedule rows store the dotted path of the task they run. The RDN tasks
# moved from digitaltwins/tasks.py to digitaltwins/rdn/tasks.py: the hourly
# reconcile row (migration 0004) and any in-flight one-off poll rows follow them.
# digitaltwins/tasks.py still re-exports the old paths for tasks queued meanwhile.
MOVED = {
    "digitaltwins.tasks.reconcile_stale_rdn_jobs": "digitaltwins.rdn.tasks.reconcile_stale_rdn_jobs",
    "digitaltwins.tasks.poll_rdn_job": "digitaltwins.rdn.tasks.poll_rdn_job",
}


def forwards(apps, schema_editor):
    # apps.get_model, not the live django_q model - see 0004.
    Schedule = apps.get_model("django_q", "Schedule")
    for old, new in MOVED.items():
        Schedule.objects.filter(func=old).update(func=new)


def backwards(apps, schema_editor):
    Schedule = apps.get_model("django_q", "Schedule")
    for old, new in MOVED.items():
        Schedule.objects.filter(func=new).update(func=old)


class Migration(migrations.Migration):

    dependencies = [
        ("digitaltwins", "0010_berexperimentrequest_archive_cancel_hide"),
        ("django_q", "__latest__"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
