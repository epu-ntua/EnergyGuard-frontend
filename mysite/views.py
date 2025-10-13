from django.core.paginator import Paginator
from django.db.models.aggregates import Sum
from django.shortcuts import render 
from datetime import datetime
import mlflow
from core.models import Dataset, Billing

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

def register(request):
    return render(request, 'mysite/registration.html', {"show_vertical_navbar": False})