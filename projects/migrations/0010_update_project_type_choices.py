from django.db import migrations, models

OLD_TO_NEW = {
    "web_app": "application",
    "mobile_app": "application",
    "iot_integration": "edge_embedded_ai",
}


def remap_forward(apps, schema_editor):
    Project = apps.get_model("experiments", "Project")
    for old_value, new_value in OLD_TO_NEW.items():
        Project.objects.filter(project_type=old_value).update(project_type=new_value)


def remap_backward(apps, schema_editor):
    Project = apps.get_model("experiments", "Project")
    Project.objects.filter(project_type="application").update(project_type="web_app")
    Project.objects.filter(project_type="edge_embedded_ai").update(project_type="iot_integration")


class Migration(migrations.Migration):

    dependencies = [
        ("experiments", "0009_remove_team_from_project"),
    ]

    operations = [
        migrations.RunPython(remap_forward, remap_backward),
        migrations.AlterField(
            model_name="project",
            name="project_type",
            field=models.CharField(
                choices=[
                    ("ai_model", "AI Model"),
                    ("ai_service", "AI Service"),
                    ("application", "Application"),
                    ("edge_embedded_ai", "Edge / Embedded AI"),
                    ("data_pipeline", "Data Pipeline"),
                    ("simulation_model", "Simulation Model"),
                    ("ai_agent_system", "AI Agent System"),
                ],
                default="ai_model",
                max_length=20,
            ),
        ),
    ]
