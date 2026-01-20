from formtools.wizard.views import SessionWizardView
from .forms import UserWizardForm, ProfileWizardForm, PaymentWizardForm, CustomAuthenticationForm, ProfileForm
from .models import User, Profile
from .utils import get_time_since_joined
from billing.models import PaymentMethod
from django.core.files.storage import FileSystemStorage
from django.shortcuts import render
from django.conf import settings
from django.shortcuts import render, redirect
from django.db import transaction
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
import os
from datetime import date


# Create your views here.
FORMS = [
    ("user_info", UserWizardForm),
    ("profile_info", ProfileWizardForm),
    ("payment_info", PaymentWizardForm)
]

TEMPLATE_NAMES = {
    "user_info": "accounts/registration-step1.html",
    "profile_info": "accounts/registration-step2.html",
    "payment_info": "accounts/registration-step3.html",
}

class RegistrationWizard(SessionWizardView):
    # Necessary to handle ImageField or FileField in forms
    file_storage = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'wizard_uploads_temp'))

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)
    
    def get_template_names(self): # Change default template names according to the current step, by overriding get_template_names method
        return [TEMPLATE_NAMES[self.steps.current]]
    
    def get_form(self, step=None, data=None, files=None): 
        form = super().get_form(step, data, files) 
        return form
    
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

        return redirect('registration_success')  
            
def registration_success(request):
    if request.user.is_authenticated:
        return redirect('home')
    # Provide a minimal wizard-like context so base template can resolve wizard.steps.current
    wizard = {"steps": {"current": "done"}}
    return render(request, 'accounts/registration-success.html', {"wizard": wizard})

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user:
                login(request, user)
                return redirect('experiment_index')
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
            if company:= form.cleaned_data.get('company'):
                user_profile.company = company
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
            'company': user_profile.company or '',
            'position': user_profile.position or '',
            'short_bio': user_profile.bio or '',
            'full_name': f"{request.user.first_name} {request.user.last_name}" or ''
        }

        if user_profile.birth_date:
            initial_data['year_of_birth'] = str(user_profile.birth_date.year)
            initial_data['month_of_birth'] = str(user_profile.birth_date.month)
            initial_data['day_of_birth'] = str(user_profile.birth_date.day)
        
        form = ProfileForm(initial=initial_data)


    return render(request, 'accounts/profile.html', {"active_navbar_page": None, "joined_display": joined_display, "last_login": last_login,  "form": form, "profile": user_profile})
