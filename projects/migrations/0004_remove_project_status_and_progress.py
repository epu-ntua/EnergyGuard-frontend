from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("experiments", "0003_rename_experiment_name_aaa840_idx_project_name_f50fde_idx"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="project",
            name="progress",
        ),
        migrations.RemoveField(
            model_name="project",
            name="status",
        ),
    ]
