from django.db import migrations, models


def add_profile_team_id(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(profile)").fetchall()]

    if "team_id" in existing_columns:
        return

    Profile = apps.get_model("accounts", "Profile")
    team_field = Profile._meta.get_field("team")
    schema_editor.add_field(Profile, team_field)


def remove_profile_team_id(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    field = Profile._meta.get_field("team")
    schema_editor.remove_field(Profile, field)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_add_team_joined_at_to_profile"),
    ]

    operations = [
        migrations.RunPython(add_profile_team_id, remove_profile_team_id),
    ]