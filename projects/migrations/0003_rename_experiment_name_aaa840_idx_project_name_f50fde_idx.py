from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("experiments", "0002_project_model_and_table_rename"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="project",
            new_name="project_name_f50fde_idx",
            old_name="experiment_name_aaa840_idx",
        ),
    ]
