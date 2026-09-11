from django.db import migrations


def grant_edit_to_existing_collaborators(apps, schema_editor):
    """Preserve today's behaviour while `permission_level` starts being enforced.

    Until now every collaborator could create and edit experiments regardless of
    `permission_level`, because the field was never read anywhere. Project.can_edit
    now honours it, so existing rows are promoted to EDIT - otherwise enforcing the
    field would silently revoke access people already had.
    New collaborators still default to VIEW.
    """
    ProjectCollaborator = apps.get_model("experiments", "ProjectCollaborator")
    ProjectCollaborator.objects.filter(permission_level="view").update(permission_level="edit")


def noop_reverse(apps, schema_editor):
    # Not reversible in a meaningful way: we cannot tell which rows were already
    # EDIT before this ran, and downgrading everyone would revoke real access.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("experiments", "0010_update_project_type_choices"),
    ]

    operations = [
        migrations.RunPython(grant_edit_to_existing_collaborators, noop_reverse),
    ]
