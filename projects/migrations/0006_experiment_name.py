from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0005_add_experiments"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
