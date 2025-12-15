from core.models import User, Profile, Dataset, Billing, PaymentMethod, Experiment
from mysite.forms import *
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import render, redirect
from django.db.models.aggregates import Sum
from django.db.models import Q
from django.db import transaction
from django.conf import settings
from django.http import JsonResponse
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

    return render(request, 'mysite/experiments-list.html', {"experiments" : filtered_data, "experiments_num": counts, "status_filter": status_filter, "active_navbar_page": "experiments", "show_vertical_navbar": True})

def error_does_not_exist(request, error=None):
    return render(request, 'mysite/error-does-not-exist.html', {"error": error})


def experiment_details(request, experiment_id):

    # Optimize query
    try:
        experiment = (
            Experiment.objects
            .select_related('creator')
            .prefetch_related('collaborators__profile')
            .get(pk=experiment_id)
        )

        experiment_details = {
        "name": experiment.name,
        "start_date": experiment.created_at,
        "last_update": experiment.updated_at,
        "status": experiment.status,
        "description": experiment.description,
        "progress": experiment.progress,
        "type": experiment.get_exp_type_display(),
        "id": experiment_id,
        "collaborators": experiment.collaborators.all(),
    }
    except Experiment.DoesNotExist:
        return redirect('error_does_not_exist', error= "Experiment not found")  # or render an error page
    
    return render(request, 'mysite/experiment-details.html', {"experiment": experiment, "exp": experiment_details,  "active_navbar_page": "experiments", "show_vertical_navbar": True})

"""def datasets_list(request):

    data = Dataset.objects.all()

    # Number of all/published/private/restricted/under_review datasets
    counts = {
        "all": data.count(),
        "published": data.filter(status="published").count(),
        "private": data.filter(status="private").count(),
        "restricted": data.filter(status="restricted").count(),
        "under_review": data.filter(status="under_review").count(),
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

    return render(request, 'mysite/dataset-list.html', {"dataset" : filtered_data, "dataset_num": counts, "status_filter": status_filter, "active_navbar_page": "datasets", "show_vertical_navbar": True})"""

def datasets_list(request):
    # DataTables AJAX branch
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("draw"):
        draw = int(request.GET.get("draw", 1))
        start = int(request.GET.get("start", 0))
        length = int(request.GET.get("length", 10))
        search_value = request.GET.get("search[value]", "")
        status_filter = request.GET.get("status")

        order_col = request.GET.get("order[0][column]", "3")
        order_dir = request.GET.get("order[0][dir]", "desc")
        column_map = {
            "1": "name",
            "2": "users__first_name",
            "3": "created_at",
            "4": "updated_at",
            "5": "label",
            "6": "source",
            "7": "status",
        }
        ordering = column_map.get(order_col, "created_at")
        if order_dir == "desc":
            ordering = f"-{ordering}"

        qs = Dataset.objects.prefetch_related("users").all()
        if status_filter in ["published", "private", "restricted", "under_review"]:
            qs = qs.filter(status=status_filter)

        records_total = qs.count()

        if search_value:
            qs = qs.filter(
                Q(name__icontains=search_value)
                | Q(label__icontains=search_value)
                | Q(source__icontains=search_value)
                | Q(status__icontains=search_value)
                | Q(users__username__icontains=search_value)
            ).distinct()

        records_filtered = qs.count()
        qs = qs.order_by(ordering)[start:start + length]

        data = []
        for d in qs:
            collaborators = ", ".join(d.users.values_list("username", flat=True)) or "No collaborators"
            data.append({
                "id": d.id,
                "name": d.name,
                "users": collaborators,
                "created_at": d.created_at.strftime("%b %d, %Y"),
                "updated_at": d.updated_at.strftime("%b %d, %Y"),
                "label": d.get_label_display(),
                "source": d.get_source_display(),
                "status": d.status,
                "status_badge": f'<span class="badge badge-phoenix fs-10 badge-phoenix-secondary"><span class="badge-label">{d.status.replace("_", " ").upper()}</span></span>',
            })

        return JsonResponse({
            "draw": draw,
            "recordsTotal": records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        })

    # Initial page render (no paginator)
    data = Dataset.objects.all()
    counts = {
        "all": data.count(),
        "published": data.filter(status="published").count(),
        "private": data.filter(status="private").count(),
        "restricted": data.filter(status="restricted").count(),
        "under_review": data.filter(status="under_review").count(),
    }
    status_filter = request.GET.get("status")
    return render(request, "mysite/datasets-list.html", {
        "dataset_num": counts,
        "status_filter": status_filter,
        "active_navbar_page": "datasets",
        "show_vertical_navbar": True,
    })

def dataset_details(request, dataset_id):

    metadata = {
        "id": ( "-" , "Unique identifier of the building record" ),
        "address": ("-", "Full address of the building"),
        "cadastre_number": ("-", "Official cadastre number of the building"),
        "construction_year": ("year", "Year when the building was constructed"),
        "total_area": ("m²", "Total area of the building in square meters"),
        "renovation_year": ("year", "Year of the last renovation"),
        "total_renovation_cost": ("€", "Total cost of renovations in euros"),
        "initial_consumption": ("kWh/m²", "Energy consumption before renovation"),
        "estimated_savings": ("%", "Estimated energy savings after renovation"),
        "achieved_savings": ("%", "Actual energy savings after renovation"),
        "initial_energy_class": ("A, B, C,...", "Energy class before renovation"),
        "final_energy_class": ("A, B, C,...", "Energy class after renovation"),
    }
    dataset = Dataset.objects.filter(pk=dataset_id).first()  # avoid exception if not found

    if dataset:
        dataset_details = {
            "id": dataset.id,
            "name": dataset.name,
            "created_at": dataset.created_at,
            "updated_at": dataset.updated_at,
            "status": dataset.status,
            "label": dataset.get_label_display(),
            "source": dataset.get_source_display(),
            "collaborators": dataset.users.all()
        }
    else:
        return redirect('error_does_not_exist', error= "Dataset not found")

    return render(request, 'mysite/dataset-details.html', {"dataset": dataset, "dt": dataset_details, "metadata": metadata, "active_navbar_page": "datasets", "show_vertical_navbar": True})

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

def collaboration_hub(request):
    return render(request, 'mysite/collaboration-hub.html', {"active_navbar_page": "collaboration_hub", "show_vertical_navbar": True})

def documentation(request):
    return render(request, 'mysite/documentation.html', {"active_navbar_page": "documentation", "show_vertical_navbar": True})