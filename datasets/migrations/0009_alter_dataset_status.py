from django.db import migrations, models


def forwards_map_dataset_statuses(apps, schema_editor):
    Dataset = apps.get_model("datasets", "Dataset")
    Dataset.objects.filter(status="published").update(status="approved")
    Dataset.objects.filter(status__in=["private", "restricted"]).update(status="under_review")


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0008_remove_dataset_downloads_users_and_users_downloads"),
    ]

    operations = [
        migrations.RunPython(forwards_map_dataset_statuses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dataset",
            name="status",
            field=models.CharField(
                choices=[
                    ("under_review", "Under Review"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="under_review",
                max_length=20,
            ),
        ),
    ]
