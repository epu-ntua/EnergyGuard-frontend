from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import DatabaseError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.views import BaseWizardView

from ..forms import ExperimentFacilitiesForm, ExperimentGeneralInfoForm, ExperimentSandboxPackagesForm
from ..models import Experiment, Project
from ..services import (
    MlflowClientError,
    create_experiment as mlflow_create_experiment,
    delete_artifacts_from_object_storage as mlflow_delete_artifacts_from_object_storage,
    delete_experiment as mlflow_delete_experiment,
    get_experiment_tags as mlflow_get_experiment_tags,
    list_experiment_runs,
    make_deleted_experiment_name as mlflow_make_deleted_experiment_name,
    set_experiment_tags as mlflow_set_experiment_tags,
    update_experiment_name as mlflow_update_experiment_name,
)
from ..services.mlflow_client import list_run_artifacts

EXPERIMENT_TEMPLATE_NAMES = {
    "0": "projects/experiment-creation-step1.html",
    "1": "projects/experiment-creation-step2.html",
    "2": "projects/experiment-creation-step3.html",
}
EXPERIMENT_FORMS = [
    ("0", ExperimentGeneralInfoForm),
    ("1", ExperimentFacilitiesForm),
    ("2", ExperimentSandboxPackagesForm),
]
EXPERIMENT_STEP_METADATA = {
    "0": {"title": "General", "icon": "fa-info-circle"},
    "1": {"title": "Facilities", "icon": "fa-building"},
    "2": {"title": "Packages", "icon": "fa-cubes-stacked"},
}


def _user_can_access_project(user, project: Project) -> bool:
    if project.creator_id == user.id:
        return True
    return project.collaborators.filter(pk=user.pk).exists()


def _get_accessible_project_or_404(user, project_id: int) -> Project:
    project = get_object_or_404(Project.objects.select_related("creator"), pk=project_id)
    if not _user_can_access_project(user, project):
        raise Http404("Project not found")
    return project


class ExperimentDeletionError(Exception):
    pass


def _delete_experiment_strict(project: Project, experiment: Experiment, user) -> None:
    if experiment.mlflow_experiment_id:
        try:
            mlflow_delete_artifacts_from_object_storage(experiment.mlflow_experiment_id)
        except MlflowClientError as exc:
            raise ExperimentDeletionError(f"failed to delete artifacts: {exc}") from exc

        try:
            mlflow_update_experiment_name(
                experiment.mlflow_experiment_id,
                mlflow_make_deleted_experiment_name(),
                user=user,
            )
            mlflow_delete_experiment(experiment.mlflow_experiment_id, user=user)
        except MlflowClientError as exc:
            raise ExperimentDeletionError(f"failed to rename/delete in MLflow: {exc}") from exc

    try:
        experiment.delete()
    except Exception as exc:
        raise ExperimentDeletionError(f"failed to delete local database record: {exc}") from exc


class AddExperimentView(LoginRequiredMixin, BaseWizardView):
    template_names = EXPERIMENT_TEMPLATE_NAMES
    step_metadata = EXPERIMENT_STEP_METADATA

    def dispatch(self, request, *args, **kwargs):
        self.project = _get_accessible_project_or_404(request.user, kwargs["project_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        context["project"] = self.project
        return context

    def done(self, form_list, **kwargs):
        general_info = form_list[0].cleaned_data
        facilities = form_list[1].cleaned_data
        packages = form_list[2].cleaned_data

        raw_tags = general_info.get("tags", "")
        tags = {tag.strip(): "true" for tag in raw_tags.split(",") if tag.strip()}
        if facilities.get("facility_name"):
            tags["facility"] = facilities["facility_name"]
        if packages.get("package_name"):
            tags["package"] = packages["package_name"]
        tags["project_id"] = str(self.project.id)
        tags["project"] = self.project.name
        tags["creator_id"] = str(self.request.user.id)

        mlflow_experiment_id = ""
        try:
            mlflow_experiment_id = mlflow_create_experiment(
                name=general_info["name"],
                tags=tags,
                user=self.request.user,
            )
            mlflow_set_experiment_tags(mlflow_experiment_id, tags, user=self.request.user)
            tags = mlflow_get_experiment_tags(mlflow_experiment_id, user=self.request.user) or tags
        except MlflowClientError as exc:
            messages.error(
                self.request,
                f"Experiment creation failed because MLflow sync failed: {exc}",
            )
            return redirect("add_experiment", project_id=self.project.id)

        with transaction.atomic():
            Experiment.objects.create(
                project=self.project,
                creator=self.request.user,
                name=general_info["name"],
                description=general_info["description"],
                tags=tags,
                mlflow_experiment_id=mlflow_experiment_id,
            )

        messages.success(self.request, "Experiment created successfully.")
        return redirect("project_details", project_id=self.project.id)


@login_required
@require_POST
def delete_project(request, project_id: int):
    project = _get_accessible_project_or_404(request.user, project_id)
    if project.creator_id != request.user.id:
        messages.error(request, "Only project owner can delete this project.")
        return redirect("project_details", project_id=project.id)

    project_name = project.name
    try:
        with transaction.atomic():
            locked_project = Project.objects.select_for_update(nowait=True).get(pk=project.id)
            experiments = list(
                Experiment.objects.select_for_update(nowait=True).filter(project_id=locked_project.id).order_by("id")
            )
            for experiment in experiments:
                _delete_experiment_strict(locked_project, experiment, request.user)
            locked_project.delete()
    except DatabaseError:
        messages.error(request, "Project deletion is already in progress. Please try again in a moment.")
        return redirect("project_details", project_id=project.id)
    except ExperimentDeletionError as exc:
        messages.error(request, f'Project "{project.name}" deletion stopped: {exc}')
        return redirect("project_details", project_id=project.id)
    except Exception as exc:
        messages.error(request, f'Project "{project_name}" deletion stopped: database delete failed: {exc}')
        return redirect("project_details", project_id=project.id)

    messages.success(request, f'Project "{project_name}" deleted successfully.')
    return redirect("projects_list")


@login_required
@require_POST
def delete_experiment(request, project_id: int, experiment_id: int):
    project = _get_accessible_project_or_404(request.user, project_id)
    experiment = get_object_or_404(Experiment, pk=experiment_id, project_id=project.id)

    if request.user.id not in {project.creator_id, experiment.creator_id}:
        messages.error(request, "You do not have permission to delete this experiment.")
        return redirect("project_details", project_id=project.id)

    try:
        with transaction.atomic():
            locked_project = Project.objects.select_for_update(nowait=True).get(pk=project.id)
            locked_experiment = Experiment.objects.select_for_update(nowait=True).get(
                pk=experiment.id,
                project_id=locked_project.id,
            )
            _delete_experiment_strict(locked_project, locked_experiment, request.user)
    except DatabaseError:
        messages.error(request, "Experiment deletion is already in progress. Please try again in a moment.")
        return redirect("project_details", project_id=project.id)
    except ExperimentDeletionError as exc:
        messages.error(request, f"Experiment deletion stopped: {exc}")
        return redirect("project_details", project_id=project.id)
    except Exception as exc:
        messages.error(request, f"Experiment deletion stopped: database delete failed: {exc}")
        return redirect("project_details", project_id=project.id)

    messages.success(request, "Experiment deleted successfully.")
    return redirect("project_details", project_id=project.id)


@login_required
def experiments_list(request, project_id: int):
    project = _get_accessible_project_or_404(request.user, project_id)
    experiments = project.experiments.select_related("creator").order_by("-updated_at")
    return render(
        request,
        "projects/experiments-list.html",
        {
            "project": project,
            "experiments": experiments,
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )


def _extract_eval_payload(experiment: Experiment, user) -> dict[str, Any]:
    if not experiment.mlflow_experiment_id:
        return {"runs": [], "images": []}

    runs = list_experiment_runs(experiment.mlflow_experiment_id, max_results=1000, user=user)
    run_rows: list[dict[str, Any]] = []
    image_rows: list[dict[str, Any]] = []

    for run in runs:
        info = run.get("info", {})
        data = run.get("data", {})
        run_id = info.get("run_id")
        metrics = {m.get("key"): m.get("value") for m in data.get("metrics", []) if m.get("key")}
        params = {p.get("key"): p.get("value") for p in data.get("params", []) if p.get("key")}
        run_tags = {t.get("key"): t.get("value") for t in data.get("tags", []) if t.get("key")}

        run_rows.append(
            {
                "run_id": run_id,
                "status": info.get("status"),
                "start_time": info.get("start_time"),
                "end_time": info.get("end_time"),
                "metrics": metrics,
                "params": params,
                "tags": run_tags,
            }
        )

        if not run_id:
            continue

        artifacts = list_run_artifacts(run_id, user=user)
        for artifact in artifacts:
            path = artifact.get("path", "")
            lowered = path.lower()
            if lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
                image_rows.append({"run_id": run_id, "path": path})

    return {"runs": run_rows, "images": image_rows}


@login_required
@require_GET
def eval_results(request, project_id: int, experiment_id: int):
    project = _get_accessible_project_or_404(request.user, project_id)
    experiment = get_object_or_404(Experiment, pk=experiment_id, project_id=project.id)

    payload: dict[str, Any] = {
        "experiment": {
            "id": experiment.id,
            "name": experiment.name,
            "description": experiment.description,
            "tags": experiment.tags,
            "mlflow_experiment_id": experiment.mlflow_experiment_id,
        }
    }
    try:
        payload.update(_extract_eval_payload(experiment, request.user))
    except MlflowClientError as exc:
        return JsonResponse({"error": str(exc), **payload}, status=502)
    return JsonResponse(payload)
