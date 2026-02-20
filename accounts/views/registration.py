import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.shortcuts import redirect, render
from formtools.wizard.views import SessionWizardView

from billing.models import PaymentMethod
from core.views import BaseWizardView

from ..forms import PaymentWizardForm, ProfileWizardForm, UserWizardForm
from ..models import Profile, User

REGISTRATION_FORMS = [
    ("user_info", UserWizardForm),
    ("profile_info", ProfileWizardForm),
    ("payment_info", PaymentWizardForm),
]
REGISTRATION_TEMPLATE_NAMES = {
    "user_info": "accounts/registration-step1.html",
    "profile_info": "accounts/registration-step2.html",
    "payment_info": "accounts/registration-step3.html",
}
REGISTRATION_STEP_METADATA = {
    "user_info": {"title": "Account", "icon": "fa-lock"},
    "profile_info": {"title": "Personal", "icon": "fa-user"},
    "payment_info": {"title": "Billing", "icon": "fa-credit-card"},
}

ENTRY_FORMS = [
    ("entry_profile_info", ProfileWizardForm),
    ("entry_payment_info", PaymentWizardForm),
]
ENTRY_TEMPLATE_NAMES = {
    "entry_profile_info": "accounts/platform-entry-step1.html",
    "entry_payment_info": "accounts/platform-entry-step2.html",
}
ENTRY_STEP_METADATA = {
    "entry_profile_info": {"title": "Profile", "icon": "fa-user"},
    "entry_payment_info": {"title": "Billing", "icon": "fa-credit-card"},
}


def _resolve_membership(version):
    membership_selected = User.Membership.FREE
    credits_amount = 100
    if version == "paid":
        membership_selected = User.Membership.PAID
        credits_amount = 500
    return membership_selected, credits_amount


def _render_wizard_success(request, step_metadata):
    wizard = {"steps": {"current": "done"}}
    wizard_steps = step_metadata.values()
    return render(
        request,
        "accounts/registration-success.html",
        {"wizard": wizard, "wizard_steps": wizard_steps},
    )


class RegistrationWizard(SessionWizardView):
    file_storage = FileSystemStorage(
        location=os.path.join(settings.MEDIA_ROOT, "wizard_uploads_temp")
    )

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        return [REGISTRATION_TEMPLATE_NAMES[self.steps.current]]

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        steps = []
        for step_name in self.steps.all:
            meta = REGISTRATION_STEP_METADATA.get(step_name, {})
            steps.append(
                {
                    "name": step_name,
                    "title": meta.get("title", step_name.replace("_", " ").title()),
                    "icon": meta.get("icon", "fa-user"),
                }
            )
        context["wizard_steps"] = steps
        return context

    def done(self, form_list, **kwargs):
        user_data = self.get_cleaned_data_for_step("user_info")
        profile_data = self.get_cleaned_data_for_step("profile_info")
        payment_data = self.get_cleaned_data_for_step("payment_info")

        version = self.request.POST.get("version")
        membership_selected, credits_amount = _resolve_membership(version)

        with transaction.atomic():
            user = User.objects.create_user(
                email=user_data["email"],
                username=user_data["email"],
                first_name=user_data["first_name"],
                last_name=user_data["last_name"],
                password=user_data["password1"],
                membership=membership_selected,
                credits=credits_amount,
            )
            Profile.objects.create(user=user, **profile_data)
            if version == "paid":
                PaymentMethod.objects.create(user=user, **payment_data)

        return redirect("platform_registration_success")


class PlatformEntryView(BaseWizardView):
    template_names = ENTRY_TEMPLATE_NAMES
    step_metadata = ENTRY_STEP_METADATA

    def done(self, form_list, **kwargs):
        profile_data = self.get_cleaned_data_for_step("entry_profile_info")
        payment_data = self.get_cleaned_data_for_step("entry_payment_info")
        version = self.request.POST.get("version")

        with transaction.atomic():
            user = self.request.user
            Profile.objects.create(user=user, **profile_data)
            if version == "paid":
                PaymentMethod.objects.create(user=user, **payment_data)

        return redirect("keycloak_registration_success")


def platform_registration_success(request, *args, **kwargs):
    return _render_wizard_success(request, REGISTRATION_STEP_METADATA)


def keycloak_registration_success(request, *args, **kwargs):
    return _render_wizard_success(request, ENTRY_STEP_METADATA)
