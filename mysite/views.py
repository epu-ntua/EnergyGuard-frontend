from core.models import User, Profile, Dataset, Billing, PaymentMethod
from mysite.forms import UserWizardForm, ProfileWizardForm, PaymentWizardForm
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.db.models.aggregates import Sum
from django.db import transaction
from django.conf import settings
from formtools.wizard.views import SessionWizardView
from datetime import datetime
import mlflow
import os

def home(request):
    return render(request, 'mysite/home.html', {})

def experiments_list(request):

    mlflow.set_tracking_uri("https://mlflow.toolbox.epu.ntua.gr/")
    
    data = []
    for exp in mlflow.search_experiments():
        created = datetime.fromtimestamp(exp.creation_time / 1000.0).date() if exp.creation_time else None
        updated = datetime.fromtimestamp(exp.last_update_time / 1000.0).date() if exp.last_update_time else None

        data.append({
            "name": exp.name,
            "start_date": created,
            "last_update": updated,
            "status": exp.lifecycle_stage,
            "artifact_uri": exp.artifact_location,
            "id": exp.experiment_id
        })

    # Number of total/active/deleted experiments
    counts = {
        "all": len(data),
        "active": sum(1 for d in data if d["status"] == "active"),
        "deleted": sum(1 for d in data if d["status"] == "deleted"),
    }

    # Sort data according to column
    sort_filter = request.GET.get('sort') 
    if sort_filter in ['name', 'start_date', 'last_update']:
        data.sort(key=lambda x: x[sort_filter]) 

    # Filter data according to status
    status_filter = request.GET.get("status")
    if status_filter in ["active", "deleted"]:
        data = [d for d in data if d["status"] == status_filter]

    # Pagination implementation for 5 experiments per page
    p = Paginator(data, 5)
    page_number = request.GET.get("page")
    filtered_data = p.get_page(page_number)

    return render(request, 'mysite/experiments_list.html', {"experiments" : filtered_data, "experiments_num": counts, "status_filter": status_filter, "active_navbar_page": "experiments", "show_vertical_navbar": True})

def datasets_list(request):

    data = Dataset.objects.all()

    # Number of all/published/private/restricted/under_review datasets
    counts = {
        "all": data.count(),
        "published": data.filter(status="published").count,
        "private": data.filter(status="private").count,
        "restricted": data.filter(status="restricted").count,
        "under_review": data.filter(status="under_review").count,
    }
    
    # Sort data according to column
    sort = request.GET.get('sort') 
    if sort in ['name', 'created_at', 'updated', 'label', 'source']:
        data = data.order_by(sort)

    # Filter data according to status
    status_filter = request.GET.get("status")
    if status_filter in ["published", "private", "restricted", "under_review"]:
        data = data.filter(status=status_filter)

    # Pagination implementation for 8 datasets per page
    p = Paginator(data, 7)
    page_number = request.GET.get("page")
    filtered_data = p.get_page(page_number)

    return render(request, 'mysite/dataset_list.html', {"dataset" : filtered_data, "dataset_num": counts, "status_filter": status_filter, "active_navbar_page": "datasets", "show_vertical_navbar": True})

def currency_format(value):
    if value == Billing.Currency.USD:
        return "$"
    elif value == Billing.Currency.GBP:
        return "£"
    elif value == Billing.Currency.EUR:
        return "€"

def billing(request):
    # active_user = request.user
    # for i in range(1, 501):
    #     customer_billing = Billing.objects.filter(customer=i)
    #     if customer_billing.exists():
    #         # billing_info = customer_billing.latest('billing_period_end')
    #         for u in customer_billing:
    #             u.currency = customer_billing[0].currency
    #             u.save()
            # currency = currency_format(billing_info.currency)
    customer_billing_info = Billing.objects.filter(customer=23)  # Replace with active_user.id in production
    if customer_billing_info.exists():
        currency = currency_format(customer_billing_info[0].currency)
        total_cost = customer_billing_info.aggregate(Sum('amount')) or 0 # Sum of all amounts for this customer
        total_cost_amount = float(total_cost["amount__sum"]) if total_cost["amount__sum"] else 0.0
    else:
        currency = "€"
        total_cost_amount = 0.0
    return render(request, 'mysite/billing.html', {"user": customer_billing_info, "active_navbar_page": "billing", "currency_format": currency, "sum": total_cost_amount, "show_vertical_navbar": True})

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

        if payment_data.get('version') == 'paid':
            membership_selected = User.Membership.PAID
            credits_amount = 500

        with transaction.atomic(): 
            user = User.objects.create_user(    # create_user method handles password hashing
                email=user_data['email'],
                username=user_data['username'],
                password=user_data['password1'],
                membership=membership_selected,
                credits=credits_amount
            )
            Profile.objects.create(user=user, **profile_data)
            PaymentMethod.objects.create(user=user, **payment_data)

        #TODO: Omit login step if email verification is implemented
        login(self.request, user)  # Automatically log the user in after successful registration

        return redirect('registration_success')  
            
def registration_success(request):
    # Provide a minimal wizard-like context so base template can resolve wizard.steps.current
    wizard = {"steps": {"current": "done"}}
    return render(request, 'mysite/registration-success.html', {"wizard": wizard})
