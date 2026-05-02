from django.db import migrations, models


def add_profile_team_role(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        existing_columns = [
            row[1] for row in cursor.execute("PRAGMA table_info(profile)").fetchall()
        ]

    if "team_role" in existing_columns:
        return

    Profile = apps.get_model("accounts", "Profile")
    team_role_field = Profile._meta.get_field("team_role")
    schema_editor.add_field(Profile, team_role_field)


def remove_profile_team_role(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    field = Profile._meta.get_field("team_role")
    schema_editor.remove_field(Profile, field)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_add_profile_team_id"),
    ]

    operations = [
        migrations.RunPython(add_profile_team_role, remove_profile_team_role),
    ]
