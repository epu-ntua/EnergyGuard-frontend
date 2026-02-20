from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0005_alter_dataset_bucket_name"),
    ]

    operations = [
        migrations.RenameField(
            model_name="dataset",
            old_name="experiments",
            new_name="projects",
        ),
    ]
