from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0004_convert_publisher_to_user_fk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dataset",
            name="bucket_name",
            field=models.CharField(default="energyguard-datasets", max_length=63),
        ),
    ]
