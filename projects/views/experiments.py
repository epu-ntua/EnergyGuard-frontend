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

from ..forms import ExperimentEditForm, ExperimentGeneralInfoForm
from ..models import Experiment, Project
from ..services import (
    MlflowClientError,
    create_experiment as mlflow_create_experiment,
    delete_artifacts_from_object_storage as mlflow_delete_artifacts_from_object_storage,
    delete_experiment as mlflow_delete_experiment,
    list_experiment_runs,
    make_deleted_experiment_name as mlflow_make_deleted_experiment_name,
    set_experiment_tags as mlflow_set_experiment_tags,
    update_experiment_name as mlflow_update_experiment_name,
)
from ..services.mlflow_client import (
    list_registered_model_versions_for_run,
    make_registered_model_links,
)

EXPERIMENT_TEMPLATE_NAMES = {
    "0": "projects/experiment-creation-step1.html",
}
EXPERIMENT_FORMS = [
    ("0", ExperimentGeneralInfoForm),
]
EXPERIMENT_STEP_METADATA = {
    "0": {"title": "General", "icon": "fa-info-circle"},
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

        raw_tags = general_info.get("tags", "")
        tags = {tag.strip(): "true" for tag in raw_tags.split(",") if tag.strip()}
        tags["project_id"] = str(self.project.id)
        tags["project"] = self.project.name
        tags["creator_id"] = str(self.request.user.id)

        mlflow_experiment_id = ""
        try:
            mlflow_experiment_id = mlflow_create_experiment(
                name=general_info["name"],
                tags={"project_name": self.project.name},
                user=self.request.user,
            )
            mlflow_set_experiment_tags(
                mlflow_experiment_id,
                {"mlflow.note.content": general_info.get("description", "")},
                user=self.request.user,
            )
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
def edit_experiment(request, project_id: int, experiment_id: int):
    project = _get_accessible_project_or_404(request.user, project_id)
    experiment = get_object_or_404(Experiment, pk=experiment_id, project_id=project.id)

    if request.user.id not in {project.creator_id, experiment.creator_id}:
        messages.error(request, "You do not have permission to edit this experiment.")
        return redirect("project_details", project_id=project.id)

    if not experiment.mlflow_experiment_id:
        messages.error(request, "This experiment is not linked to MLflow and cannot be edited.")
        return redirect("project_details", project_id=project.id)

    if request.method == "POST":
        form = ExperimentEditForm(request.POST)
        if form.is_valid():
            try:
                mlflow_update_experiment_name(
                    experiment.mlflow_experiment_id,
                    form.cleaned_data["name"],
                    user=request.user,
                )
                mlflow_set_experiment_tags(
                    experiment.mlflow_experiment_id,
                    {"mlflow.note.content": form.cleaned_data.get("description", "")},
                    user=request.user,
                )
            except MlflowClientError as exc:
                messages.error(request, f"Experiment update failed because MLflow sync failed: {exc}")
                return redirect("edit_experiment", project_id=project.id, experiment_id=experiment.id)

            messages.success(request, "Experiment updated successfully.")
            return redirect("project_details", project_id=project.id)
    else:
        form = ExperimentEditForm(
            initial={
                "name": experiment.name,
                "description": experiment.description,
            }
        )

    return render(
        request,
        "projects/experiment-edit.html",
        {
            "project": project,
            "experiment": experiment,
            "form": form,
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )


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
        return {
            "latest_run_metrics": {},
            "best_metrics": {},
            "all_run_metrics_chronological": [],
            "registered_models": [],
        }

    runs = list_experiment_runs(experiment.mlflow_experiment_id, max_results=1000, user=user)
    run_rows: list[dict[str, Any]] = []

    for run in runs:
        info = run.get("info", {})
        data = run.get("data", {})
        run_id = info.get("run_id")
        metrics = {m.get("key"): m.get("value") for m in data.get("metrics", []) if m.get("key")}
        # params = {p.get("key"): p.get("value") for p in data.get("params", []) if p.get("key")}
        # run_tags = {t.get("key"): t.get("value") for t in data.get("tags", []) if t.get("key")}

        run_rows.append(
            {
                "run_id": run_id,
                "status": info.get("status"),
                "start_time": info.get("start_time"),
                "end_time": info.get("end_time"),
                "metrics": metrics,
                # "params": params,
                # "tags": run_tags,
            }
        )

    # MLflow search API returns newest first; normalize to chronological.
    run_rows.sort(key=lambda row: (row.get("start_time") or 0, row.get("end_time") or 0))

    latest_run_metrics = run_rows[-1] if run_rows else {}

    best_metrics: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        for metric_name, metric_value in (row.get("metrics") or {}).items():
            try:
                numeric_value = float(metric_value)
            except (TypeError, ValueError):
                continue
            current_best = best_metrics.get(metric_name)
            # TODO: Change to comply with the metric (for some larger is better)
            if current_best is None or numeric_value < current_best["value"]:
                best_metrics[metric_name] = {
                    "value": numeric_value,
                    "run_id": row.get("run_id"),
                }

    registered_models: list[dict[str, Any]] = []
    seen_models: set[tuple[str, str]] = set()
    for row in run_rows:
        run_id = row.get("run_id")
        if not run_id:
            continue
        for version in list_registered_model_versions_for_run(run_id, user=user):
            name = str(version.get("name") or "").strip()
            model_version = str(version.get("version") or "").strip()
            if not name:
                continue
            dedup_key = (name, model_version)
            if dedup_key in seen_models:
                continue
            seen_models.add(dedup_key)
            links = make_registered_model_links(name, model_version or None)
            registered_models.append(
                {
                    "name": name,
                    "version": model_version,
                    "run_id": version.get("run_id") or run_id,
                    "source": version.get("source", ""),
                    "model_link": links["model_link"],
                    "model_version_link": links["model_version_link"],
                }
            )

    return {
        "latest_run_metrics": latest_run_metrics,
        "best_metrics": best_metrics,
        "all_run_metrics_chronological": [
            {"run_id": row.get("run_id"), "metrics": row.get("metrics") or {}}
            for row in run_rows
        ],
        "registered_models": registered_models,
    }


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


@login_required
@require_GET
def eval_results_all(request, project_id: int):
    project = _get_accessible_project_or_404(request.user, project_id)
    experiments = project.experiments.all().order_by("id")

    latest_run_metrics: dict[str, Any] = {}
    best_metrics: dict[str, dict[str, Any]] = {}
    all_run_metrics_chronological: list[dict[str, Any]] = []
    registered_models: list[dict[str, Any]] = []
    seen_models: set[tuple[str, str]] = set()

    for experiment in experiments:
        extracted = _extract_eval_payload(experiment, request.user)
        experiment_ref = {
            "experiment_id": experiment.id,
            "experiment_name": experiment.name,
        }

        candidate_latest = extracted.get("latest_run_metrics") or {}
        if candidate_latest:
            candidate_latest = {**candidate_latest, **experiment_ref}
            if not latest_run_metrics:
                latest_run_metrics = candidate_latest
            else:
                latest_key = (
                    latest_run_metrics.get("start_time") or 0,
                    latest_run_metrics.get("end_time") or 0,
                )
                candidate_key = (
                    candidate_latest.get("start_time") or 0,
                    candidate_latest.get("end_time") or 0,
                )
                if candidate_key > latest_key:
                    latest_run_metrics = candidate_latest

        for metric_name, metric_data in (extracted.get("best_metrics") or {}).items():
            current_best = best_metrics.get(metric_name)
            candidate_value = metric_data.get("value")
            try:
                candidate_numeric = float(candidate_value)
            except (TypeError, ValueError):
                continue
            if current_best is None or candidate_numeric < float(current_best["value"]):
                best_metrics[metric_name] = {
                    "value": candidate_numeric,
                    "run_id": metric_data.get("run_id"),
                    **experiment_ref,
                }

        all_run_metrics_chronological.extend(
            [{**row, **experiment_ref} for row in (extracted.get("all_run_metrics_chronological") or [])]
        )

        for model in extracted.get("registered_models") or []:
            dedup_key = (str(model.get("name") or ""), str(model.get("version") or ""))
            if dedup_key in seen_models:
                continue
            seen_models.add(dedup_key)
            registered_models.append({**model, **experiment_ref})

    return JsonResponse(
        {
            "latest_run_metrics": latest_run_metrics,
            "best_metrics": best_metrics,
            "all_run_metrics_chronological": all_run_metrics_chronological,
            "registered_models": registered_models,
        }
    )
