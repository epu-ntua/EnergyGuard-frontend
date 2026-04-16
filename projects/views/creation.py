from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.contrib import messages
from django.shortcuts import redirect, render

from core.views import BaseWizardView

from ..forms import ProjectFacilitiesForm, ProjectGeneralInfoForm, ProjectSandboxPackagesForm
from ..models import Experiment, Project
from ..services import (
    MlflowClientError,
    create_experiment_permission as mlflow_create_experiment_permission,
    create_experiment as mlflow_create_experiment,
    delete_experiment as mlflow_delete_experiment,
    make_deleted_experiment_name as mlflow_make_deleted_experiment_name,
    set_experiment_tags as mlflow_set_experiment_tags,
    update_experiment_name as mlflow_update_experiment_name,
)

import logging

logger = logging.getLogger(__name__)


def _cleanup_mlflow_experiment(experiment_id: str, user) -> None:
    """Best-effort cleanup of an MLflow experiment after a failure."""
    try:
        mlflow_update_experiment_name(experiment_id, mlflow_make_deleted_experiment_name(), user=user)
        mlflow_delete_experiment(experiment_id, user=user)
    except Exception:
        logger.warning("Failed to clean up MLflow experiment %s", experiment_id, exc_info=True)

PROJECT_TEMPLATE_NAMES = {
    "0": "projects/project-creation-step1.html",
    "1": "projects/project-creation-step2.html",
    "2": "projects/project-creation-step3.html",
}
PROJECT_FORMS = [
    ("0", ProjectGeneralInfoForm),
    ("1", ProjectFacilitiesForm),
    ("2", ProjectSandboxPackagesForm),
]
PROJECT_STEP_METADATA = {
    "0": {"title": "General", "icon": "fa-info-circle"},
    "1": {"title": "Facilities", "icon": "fa-building"},
    "2": {"title": "Packages", "icon": "fa-cubes-stacked"},
}


class AddProjectView(LoginRequiredMixin, BaseWizardView):
    template_names = PROJECT_TEMPLATE_NAMES
    step_metadata = PROJECT_STEP_METADATA
    cancel_url = "/projects/list/"

    def done(self, form_list, **kwargs):
        general_info = form_list[0].cleaned_data

        # --- 1. Create the MLflow experiment first (external, not transactional) ---
        default_experiment_name = f"{general_info['name']}-default"
        mlflow_experiment_id = ""
        try:
            while True:
                try:
                    mlflow_experiment_id = mlflow_create_experiment(
                        name=default_experiment_name,
                        tags={"project_name": general_info["name"]},
                        user=self.request.user,
                    )
                    mlflow_set_experiment_tags(
                        mlflow_experiment_id,
                        {"mlflow.note.content": "Default experiment created with the project."},
                        user=self.request.user,
                        use_service_credentials=True,
                    )
                    mlflow_create_experiment_permission(mlflow_experiment_id, self.request.user.email)
                    break
                except MlflowClientError as exc:
                    error_text = str(exc).lower()
                    if "already exists" in error_text or "resource_already_exists" in error_text:
                        default_experiment_name += "-"
                        continue
                    raise
        except MlflowClientError as exc:
            # Clean up the MLflow experiment if it was partially created
            if mlflow_experiment_id:
                _cleanup_mlflow_experiment(mlflow_experiment_id, self.request.user)
            messages.error(self.request, f"Project creation failed: MLflow sync failed: {exc}")
            return redirect("project_creation")

        # --- 2. Persist to DB; if this fails, clean up MLflow ---
        try:
            with transaction.atomic():
                project = Project.objects.create(
                    name=general_info["name"],
                    description=general_info["description"],
                    project_type=general_info["project_type"],
                    creator=self.request.user,
                )
                Experiment.objects.create(
                    project=project,
                    creator=self.request.user,
                    name=default_experiment_name,
                    mlflow_experiment_id=mlflow_experiment_id,
                )
        except Exception as exc:
            _cleanup_mlflow_experiment(mlflow_experiment_id, self.request.user)
            messages.error(self.request, f"Project creation failed: {exc}")
            return redirect("project_creation")

        return redirect("project_creation_success")


@login_required
def project_creation_success(request):
    if not request.session.pop("project_creation_success", False):
        return redirect("project_creation")
    wizard = {"steps": {"current": "done", "index": 0}}
    wizard_steps = PROJECT_STEP_METADATA.values()
    return render(
        request,
        "projects/project-creation-success.html",
        {
            "wizard": wizard,
            "wizard_steps": wizard_steps,
            "cancel_url": "/projects/list/",
        },
    )

