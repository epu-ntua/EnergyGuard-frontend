from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('experiments', '0008_add_team_to_project'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='project',
            name='team',
        ),
    ]
