from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render

from core.views import BaseWizardView

from ..forms import ProjectFacilitiesForm, ProjectGeneralInfoForm, ProjectSandboxPackagesForm
from ..models import Project

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

        with transaction.atomic():
            Project.objects.create(
                name=general_info["name"],
                description=general_info["description"],
                project_type=general_info["project_type"],
                creator=self.request.user,
            )

        return redirect("project_creation_success")


@login_required
def project_creation_success(request):
    wizard = {"steps": {"current": "done"}}
    wizard_steps = PROJECT_STEP_METADATA.values()
    return render(
        request,
        "projects/project-creation-success.html",
        {"wizard": wizard, "wizard_steps": wizard_steps},
    )
