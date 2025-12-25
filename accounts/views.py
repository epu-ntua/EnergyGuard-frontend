from django.shortcuts import render
from .models import User, Profile
from billing.models import PaymentMethod
from .forms import UserWizardForm, ProfileWizardForm, PaymentWizardForm, CustomAuthenticationForm
from django.core.files.storage import FileSystemStorage
from formtools.wizard.views import SessionWizardView
from django.conf import settings
from django.shortcuts import render, redirect
from django.db import transaction
from django.contrib.auth import login

# Create your views here.
FORMS = [
    ("user_info", UserWizardForm),
    ("profile_info", ProfileWizardForm),
    ("payment_info", PaymentWizardForm)
]

TEMPLATE_NAMES = {
    "user_info": "mysite/registration-step1.html",
    "profile_info": "mysite/registration-step2.html",
    "payment_info": "mysite/registration-step3.html",
}

class RegistrationWizard(SessionWizardView):
    # Necessary to handle ImageField or FileField in forms
    file_storage = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'wizard_uploads_temp'))

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
    # Provide a minimal wizard-like context so base template can resolve wizard.steps.current
    wizard = {"steps": {"current": "done"}}
    return render(request, 'mysite/registration-success.html', {"wizard": wizard})

def login_view(request):
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user:
                login(request, user)
                return redirect('home')
    else:
        form = CustomAuthenticationForm()

    return render(request, 'mysite/login.html', {'form': form})
