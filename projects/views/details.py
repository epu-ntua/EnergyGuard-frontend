from datetime import datetime, timezone as dt_timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from ..models import Project
from ..services import MlflowClientError, list_experiment_runs


def _latest_project_run_datetime(project: Project, user):
    latest_start_time_ms: int | None = None

    for experiment in project.experiments.only("mlflow_experiment_id").all():
        mlflow_experiment_id = (experiment.mlflow_experiment_id or "").strip()
        if not mlflow_experiment_id:
            continue

        try:
            runs = list_experiment_runs(mlflow_experiment_id, max_results=1, user=user)
        except MlflowClientError:
            continue

        if not runs:
            continue

        start_time = runs[0].get("info", {}).get("start_time")
        try:
            start_time_ms = int(start_time)
        except (TypeError, ValueError):
            continue

        if latest_start_time_ms is None or start_time_ms > latest_start_time_ms:
            latest_start_time_ms = start_time_ms

    if latest_start_time_ms is None:
        return None

    return timezone.localtime(
        datetime.fromtimestamp(latest_start_time_ms / 1000, tz=dt_timezone.utc)
    )


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
    latest_run_datetime = _latest_project_run_datetime(project, request.user)

    project_details_data = {
        "name": project.name,
        "start_date": project.created_at,
        "last_update": latest_run_datetime,
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
