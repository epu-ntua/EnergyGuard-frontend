from formtools.wizard.views import SessionWizardView
from .forms import *
from .models import User, Profile
from .utils import get_time_since_joined
from core.views import BaseWizardView
from billing.models import PaymentMethod
from django.core.files.storage import FileSystemStorage
from django.shortcuts import render
from django.conf import settings
from django.shortcuts import render, redirect
from django.db import transaction
from django.contrib.auth import login, logout as django_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from allauth.socialaccount.signals import pre_social_login
from allauth.socialaccount.models import SocialAccount
from django.dispatch import receiver
from django.views.decorators.http import require_POST
from urllib.parse import urlencode
import os
from datetime import date
from .keycloak_admin import KeycloakAdminClient
import logging

# Get an instance of a logger
logger = logging.getLogger(__name__)

# Create your views here.

# Registration Wizard
REGISTRATION_FORMS = [
    ("user_info", UserWizardForm),
    ("profile_info", ProfileWizardForm),
    ("payment_info", PaymentWizardForm)
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

# Platform Entry Wizard
ENTRY_FORMS = [
    ("entry_profile_info", ProfileWizardForm),
    ("entry_payment_info", PaymentWizardForm)
]
ENTRY_TEMPLATE_NAMES = {
    "entry_profile_info": "accounts/platform-entry-step1.html",
    "entry_payment_info": "accounts/platform-entry-step2.html",
}

ENTRY_STEP_METADATA = {
    "entry_profile_info": {"title": "Profile", "icon": "fa-user"},
    "entry_payment_info": {"title": "Billing", "icon": "fa-credit-card"},
}

class RegistrationWizard(SessionWizardView):
    # Necessary to handle ImageField or FileField in forms
    file_storage = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'wizard_uploads_temp'))

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)
    
    def get_template_names(self): # Change default template names according to the current step, by overriding get_template_names method
        return [REGISTRATION_TEMPLATE_NAMES[self.steps.current]]
    
    def get_form(self, step=None, data=None, files=None): 
        form = super().get_form(step, data, files) 
        return form

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

        user_data = self.get_cleaned_data_for_step('user_info') # Retrieve cleaned data from each step
        profile_data = self.get_cleaned_data_for_step('profile_info')
        payment_data = self.get_cleaned_data_for_step('payment_info')

        membership_selected = User.Membership.FREE
        credits_amount = 100

        version = self.request.POST.get('version')
        if version == 'paid':
            membership_selected = User.Membership.PAID
            credits_amount = 500

        with transaction.atomic(): 
            user = User.objects.create_user(    # create_user method handles password hashing
                email=user_data['email'],
                # Auto-generate username from email for AbstractUser compatibility
                username=user_data['email'],
                first_name=user_data['first_name'],
                last_name=user_data['last_name'],
                password=user_data['password1'],
                membership=membership_selected,
                credits=credits_amount
            )
            Profile.objects.create(user=user, **profile_data)
            if version == 'paid':
                PaymentMethod.objects.create(user=user, **payment_data)
        
        return redirect('platform_registration_success')
            
def platform_registration_success(request, *args, **kwargs):
    # Provide a minimal wizard-like context so base template can resolve wizard.steps.current
    wizard = {"steps": {"current": "done"}}
    wizard_steps = REGISTRATION_STEP_METADATA.values()
    return render(request, 'accounts/registration-success.html', {"wizard": wizard, "wizard_steps": wizard_steps})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user:
                login(request, user)
                return redirect('dashboard')
    else:
        form = CustomAuthenticationForm()

    return render(request, 'accounts/login.html', {'form': form})

@login_required
def profile(request):
    # Get time since joined using utility function
    joined_display = get_time_since_joined(request.user.date_joined)
    last_login = get_time_since_joined(request.user.last_login)
    
    # Get or create the user's profile
    user_profile, created = Profile.objects.get_or_create(user=request.user)
    user_experiments_count = request.user.creator_experiments.count()

    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            year_of_birth = form.cleaned_data.get('year_of_birth')
            month_of_birth = form.cleaned_data.get('month_of_birth')
            day_of_birth = form.cleaned_data.get('day_of_birth')

            # Update Profile model
            if full_name := form.cleaned_data.get('full_name'):
                name_parts = full_name.split()
                if len(name_parts) >= 2:
                    request.user.first_name = name_parts[0]
                    # TODO: Check this again
                    # Handle middle names
                    request.user.last_name = ' '.join(name_parts[1:])
                    request.user.save()

                    # Sync with Keycloak
                    keycloak_client = KeycloakAdminClient()
                    if keycloak_client.token:
                        user_data = {
                            "first_name": request.user.first_name,
                            "last_name": request.user.last_name,
                        }
                        result = keycloak_client.update_user(request.user, user_data)
                        if result.get("error"):
                            logger.error(f"Keycloak sync failed for user {request.user.id}: {result.get('error')}")
                    else:
                        logger.error(f"Keycloak client not initialized for user {request.user.id}. Sync failed.")

            if team:= form.cleaned_data.get('team'):
                user_profile.team = team
            if position:= form.cleaned_data.get('position'):
                user_profile.position = position
            # Convert string values to integers and create date object
            # Check that values are not empty strings
            if year_of_birth and year_of_birth != '' and month_of_birth and month_of_birth != '' and day_of_birth and day_of_birth != '':
                try:
                    user_profile.birth_date = date(int(year_of_birth), int(month_of_birth), int(day_of_birth))
                except (ValueError, TypeError) as e:
                    pass  # Skip if invalid date
            if short_bio:= form.cleaned_data.get('short_bio'):
                user_profile.bio = short_bio
            user_profile.save()
            return redirect('profile')
    else:
        initial_data = {
            'team': user_profile.team or '',
            'position': user_profile.position or '',
            'short_bio': user_profile.bio or '',
            'full_name': f"{request.user.first_name} {request.user.last_name}" or ''
        }

        if user_profile.birth_date:
            initial_data['year_of_birth'] = str(user_profile.birth_date.year)
            initial_data['month_of_birth'] = str(user_profile.birth_date.month)
            initial_data['day_of_birth'] = str(user_profile.birth_date.day)
        
        form = ProfileForm(initial=initial_data)


    return render(request, 'accounts/profile.html', {"show_sidebar": False, "joined_display": joined_display, "last_login": last_login, "form": form, "profile": user_profile, "total_experiments": user_experiments_count})

@login_required
def update_profile_picture(request):
    if request.method == 'POST':
        # Get the old picture path before it gets updated
        old_picture_path = request.user.profile.profile_picture.path if request.user.profile.profile_picture else None
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)
        if form.is_valid():
            # Delete old profile picture if it exists
            if old_picture_path and os.path.exists(old_picture_path):
                os.remove(old_picture_path)
            form.save()
    return redirect('profile')

class PlatformEntryView(BaseWizardView):
    template_names = ENTRY_TEMPLATE_NAMES
    step_metadata = ENTRY_STEP_METADATA
    
    def done(self, form_list, **kwargs):
        print("Entering done method of PlatformEntryView") # Debugging line

        profile_data = self.get_cleaned_data_for_step('entry_profile_info')
        payment_data = self.get_cleaned_data_for_step('entry_payment_info')

        membership_selected = User.Membership.FREE
        credits_amount = 100

        version = self.request.POST.get('version')
        if version == 'paid':
            membership_selected = User.Membership.PAID
            credits_amount = 500

        with transaction.atomic(): 
            user = self.request.user
            print(user)
            Profile.objects.create(user=user, **profile_data)
            if version == 'paid':
                PaymentMethod.objects.create(user=user, **payment_data)

        return redirect('keycloak_registration_success') 

def keycloak_registration_success(request, *args, **kwargs):
    # Provide a minimal wizard-like context so base template can resolve wizard.steps.current
    wizard = {"steps": {"current": "done"}}
    wizard_steps = ENTRY_STEP_METADATA.values()
    return render(request, 'accounts/registration-success.html', {"wizard": wizard, "wizard_steps": wizard_steps})

# ----------------Keycloak---------------- #


# Signal handler to track new Keycloak signups
# @receiver(pre_social_login)
# def keycloak_signup_signal(sender, request, sociallogin, **kwargs):
#     """
#     Signal fired before social login completes.
#     Marks new signups in the session.
#     """
#     if sociallogin.account.provider == 'keycloak':
#         # Check if this is a new user (doesn't have a user object yet)
#         if not sociallogin.is_existing:
#             request.session['keycloak_new_signup'] = True

# def keycloak_redirect(request):
#     """
#     Custom redirect handler for Keycloak login/signup.
#     Redirects new signups to platform entry wizard
#     Redirects existing users to experiments
#     """
#     if not request.user.is_authenticated:
#         return redirect('login')
    
#     is_new_signup = request.session.pop('keycloak_new_signup', False)
    
#     # Also check if user has a profile - new users won't have one
#     has_profile = Profile.objects.filter(user=request.user).exists()
    
#     if is_new_signup or not has_profile:
#         # New user signup - redirect to platform entry wizard
#         return redirect('platform_entry')
#     else:
#         # Existing user login - redirect to experiments
#         return redirect('experiment_index')

@require_POST   # Only allow POST requests for logout
def keycloak_logout(request):
    post_logout_redirect_uri = request.build_absolute_uri(getattr(settings, "LOGOUT_REDIRECT_URL", "/") or "/") 
    end_session_url = None
    client_id = None

    provider_config = (settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {}).get("APPS", [{}])[0])
    server_url = provider_config.get("settings", {}).get("server_url")
    client_id = provider_config.get("client_id")

    if server_url:
        end_session_url = f"{server_url}/protocol/openid-connect/logout"

    if not end_session_url:
        return redirect(post_logout_redirect_uri)

    django_logout(request)

    params = {"post_logout_redirect_uri": post_logout_redirect_uri}
    if client_id:
        params["client_id"] = client_id

    return redirect(f"{end_session_url}?{urlencode(params)}")
