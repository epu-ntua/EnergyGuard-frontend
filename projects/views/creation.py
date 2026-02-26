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
    get_experiment_tags as mlflow_get_experiment_tags,
    set_experiment_tags as mlflow_set_experiment_tags,
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
        mlflow_tags = default_tags.copy()
        with transaction.atomic():
            project = Project.objects.create(
                name=general_info["name"],
                description=general_info["description"],
                project_type=general_info["project_type"],
                creator=self.request.user,
            )
            try:
                #TODO: Fix failure if experiment already exists
                mlflow_experiment_id = mlflow_create_experiment(
                    name=f"{project.name}-default",
                    tags=default_tags,
                    user=self.request.user,
                )
                mlflow_set_experiment_tags(mlflow_experiment_id, default_tags, user=self.request.user)
                mlflow_tags = mlflow_get_experiment_tags(mlflow_experiment_id, user=self.request.user) or default_tags
            except MlflowClientError as exc:
                messages.warning(
                    self.request,
                    f"Project created, but initial MLflow experiment sync failed: {exc}",
                )

            Experiment.objects.create(
                project=project,
                creator=self.request.user,
                name="default",
                description="Default experiment created with the project.",
                tags=mlflow_tags,
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
