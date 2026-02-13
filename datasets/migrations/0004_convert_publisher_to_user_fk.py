from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forward_copy_publisher_to_fk(apps, schema_editor):
    Dataset = apps.get_model("datasets", "Dataset")
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    UserModel = apps.get_model(app_label, model_name)

    for dataset in Dataset.objects.all().iterator():
        raw_publisher = (dataset.publisher or "").strip()
        if not raw_publisher:
            continue

        user = UserModel.objects.filter(email__iexact=raw_publisher).first()
        if user is None:
            user = UserModel.objects.filter(username__iexact=raw_publisher).first()

        if user is not None:
            dataset.publisher_fk_id = user.pk
            dataset.save(update_fields=["publisher_fk"])


def reverse_copy_publisher_to_fk(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0003_dataset_bucket_name_dataset_metadata_file_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="dataset",
            name="publisher_fk",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="published_datasets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(forward_copy_publisher_to_fk, reverse_copy_publisher_to_fk),
        migrations.RemoveField(
            model_name="dataset",
            name="publisher",
        ),
        migrations.RenameField(
            model_name="dataset",
            old_name="publisher_fk",
            new_name="publisher",
        ),
    ]
