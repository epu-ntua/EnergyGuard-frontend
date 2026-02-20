import os
import tempfile

from django.core.files.storage import FileSystemStorage
from django.shortcuts import redirect
from formtools.wizard.views import SessionWizardView


class BaseWizardView(SessionWizardView):
    file_storage = FileSystemStorage(
        location=os.path.join(tempfile.gettempdir(), "energyguard_wizard_uploads_temp")
    )
    template_names = {}
    step_metadata = {}

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        return [self.template_names[self.steps.current]]

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        steps = []
        for step_name in self.steps.all:
            meta = self.step_metadata.get(step_name, {})
            steps.append(
                {
                    "name": step_name,
                    "title": meta.get("title", step_name.replace("_", " ").title()),
                    "icon": meta.get("icon", "fa-user"),
                }
            )
        context["wizard_steps"] = steps
        return context
