from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0007_rename_dataset_experiments_m2m_table"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dataset",
            name="downloads",
        ),
        migrations.RemoveField(
            model_name="dataset",
            name="users",
        ),
        migrations.RemoveField(
            model_name="dataset",
            name="users_downloads",
        ),
    ]
