from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..models import Project


@login_required
def project_details(request, project_id):
    try:
        project = (
            Project.objects.select_related("creator")
            .prefetch_related("collaborators__profile")
            .get(pk=project_id)
        )
    except Project.DoesNotExist:
        messages.error(request, "Project not found")
        return redirect("home")

    experiments = project.experiments.select_related("creator").order_by("-updated_at")
    latest_experiment = experiments.first()

    project_details_data = {
        "name": project.name,
        "start_date": project.created_at,
        "last_update": project.updated_at,
        "description": project.description,
        "type": project.get_project_type_display(),
        "id": project_id,
        "collaborators": project.collaborators.all(),
        "visibility": project.visibility,
        "team": project.creator.profile.team if hasattr(project.creator, "profile") else None,
        "mlflow_experiment_id": (
            latest_experiment.mlflow_experiment_id if latest_experiment else ""
        ),
    }
    return render(
        request,
        "projects/project-details.html",
        {
            "project_details": project_details_data,
            "experiments": experiments,
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )


@login_required
def project_index(request):
    return render(
        request,
        "projects/project-index.html",
        {
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )
