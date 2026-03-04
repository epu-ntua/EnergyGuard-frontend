from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0006_drop_experiment_tags_column"),
        ("experiments", "0006_experiment_name"),
    ]

    operations = []
