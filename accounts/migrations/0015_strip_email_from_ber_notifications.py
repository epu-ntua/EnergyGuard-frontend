import re

from django.db import migrations

# Written by digitaltwins/ber/tasks.py before it stopped naming the requester
OLD_MESSAGE = re.compile(r'^(New BER experiment request #\d+) from .+$')


def strip_requester_email(apps, schema_editor):
    Notification = apps.get_model("accounts", "Notification")
    for notification in Notification.objects.filter(message__regex=OLD_MESSAGE.pattern):
        notification.message = OLD_MESSAGE.sub(r'\1', notification.message)
        notification.save(update_fields=["message"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_schedule_due_deletion_reminders"),
    ]

    operations = [
        # Not reversible in content: the emails are gone
        migrations.RunPython(strip_requester_email, migrations.RunPython.noop),
    ]
