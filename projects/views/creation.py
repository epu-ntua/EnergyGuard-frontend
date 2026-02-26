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
    create_experiment as mlflow_create_experiment,
)

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

    def done(self, form_list, **kwargs):
        general_info = form_list[0].cleaned_data
        facilities = form_list[1].cleaned_data
        packages = form_list[2].cleaned_data

        project = None
        default_tags = {
            "project_type": general_info["project_type"],
            "project_name": general_info["name"],
            "creator_id": str(self.request.user.id),
        }
        if facilities.get("facility_name"):
            default_tags["facility"] = facilities["facility_name"]
        if packages.get("package_name"):
            default_tags["package"] = packages["package_name"]

        mlflow_experiment_id = ""
        with transaction.atomic():
            project = Project.objects.create(
                name=general_info["name"],
                description=general_info["description"],
                project_type=general_info["project_type"],
                creator=self.request.user,
            )
            try:
                default_experiment_name = f"{project.name}-default"
                while True:
                    try:
                        mlflow_experiment_id = mlflow_create_experiment(
                            name=default_experiment_name,
                            tags={"project_name": project.name},
                            user=self.request.user,
                        )
                        break
                    except MlflowClientError as exc:
                        error_text = str(exc).lower()
                        if "already exists" in error_text or "resource_already_exists" in error_text:
                            default_experiment_name += "-"
                            continue
                        raise
            except MlflowClientError as exc:
                messages.warning(
                    self.request,
                    f"Project created, but initial MLflow experiment sync failed: {exc}",
                )

            Experiment.objects.create(
                project=project,
                creator=self.request.user,
                tags=default_tags,
                mlflow_experiment_id=mlflow_experiment_id,
            )

        return redirect("project_creation_success")


@login_required
def project_creation_success(request):
    return render(
        request,
        "projects/project-creation-success.html",
        {
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )

