from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):
    """DtResult is only the record of a JupyterHub export now. The table keeps its
    name (Meta.db_table), so this renames the model and nothing in the database."""

    dependencies = [
        ('digitaltwins', '0012_dtrun'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(old_name='DtResult', new_name='DtExport'),
        migrations.AlterModelOptions(
            name='dtexport',
            options={'verbose_name': 'DT Export', 'verbose_name_plural': 'DT Exports'},
        ),
    ]
