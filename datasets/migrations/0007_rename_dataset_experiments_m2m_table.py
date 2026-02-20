from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0006_rename_experiments_projects"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE dataset_experiments RENAME TO dataset_projects;",
            reverse_sql="ALTER TABLE dataset_projects RENAME TO dataset_experiments;",
        ),
    ]
