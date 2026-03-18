from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_teaminvite'),
    ]

    operations = [
        migrations.AddField(
            model_name='teaminvite',
            name='declined_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
