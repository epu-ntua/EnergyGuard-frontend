from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("datasets", "0001_initial"),
        ("experiments", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Experiment",
            new_name="Project",
        ),
        migrations.RenameModel(
            old_name="ExperimentCollaborator",
            new_name="ProjectCollaborator",
        ),
        migrations.RenameField(
            model_name="project",
            old_name="exp_type",
            new_name="project_type",
        ),
        migrations.RenameField(
            model_name="projectcollaborator",
            old_name="experiment",
            new_name="project",
        ),
        migrations.AlterModelTable(
            name="project",
            table="project",
        ),
        migrations.AlterModelTable(
            name="projectcollaborator",
            table="project_collaborator",
        ),
        migrations.AlterModelOptions(
            name="project",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Project",
                "verbose_name_plural": "Projects",
            },
        ),
        migrations.AlterModelOptions(
            name="projectcollaborator",
            options={
                "verbose_name": "Project Collaborator",
                "verbose_name_plural": "Project Collaborators",
            },
        ),
        migrations.AlterField(
            model_name="project",
            name="collaborators",
            field=models.ManyToManyField(
                related_name="collaborator_projects",
                through="experiments.ProjectCollaborator",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="project",
            name="creator",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="creator_projects",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="project",
            name="project_type",
            field=models.CharField(
                choices=[
                    ("ai_model", "AI Model"),
                    ("ai_service", "AI Service"),
                    ("web_app", "Web Application"),
                    ("mobile_app", "Mobile Application"),
                    ("iot_integration", "IoT Integration"),
                    ("data_pipeline", "Data Pipeline"),
                ],
                default="ai_model",
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="projectcollaborator",
            name="unique_person_experiment",
        ),
        migrations.AddConstraint(
            model_name="projectcollaborator",
            constraint=models.UniqueConstraint(
                fields=("collaborator", "project"),
                name="unique_person_project",
            ),
        ),
    ]
