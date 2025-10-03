from django.core.paginator import Paginator
from django.shortcuts import render 
from datetime import datetime
import mlflow
from core.models import Dataset

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

    # Filter data according to status
    status_filter = request.GET.get("status")
    if status_filter in ["active", "deleted"]:
        filtered_data = [d for d in data if d["status"] == status_filter]
    else:
        filtered_data = data

    # Pagination implementation for 5 experiments per page
    p = Paginator(filtered_data, 5)
    page_number = request.GET.get("page")
    filtered_data = p.get_page(page_number)

    return render(request, 'mysite/experiments_list.html', {"experiments" : filtered_data, "experiments_num": counts, "status_filter": status_filter, "active_navbar_page": "experiments"})

def datasets_list(request):

    data = Dataset.objects.all()

    # Number of published/private/restricted/under_review datasets
    counts = {
        "all": data.count(),
        "published": data.filter(status="published").count,
        "private": data.filter(status="private").count,
        "restricted": data.filter(status="restricted").count,
        "under_review": data.filter(status="under_review").count,
    }

    # Filter data according to status
    status_filter = request.GET.get("status")
    if status_filter in ["published", "private", "restricted", "under_review"]:
        filtered_data = data.filter(status=status_filter)
    else:
        filtered_data = data

    # Pagination implementation for 8 datasets per page
    p = Paginator(filtered_data, 7)
    page_number = request.GET.get("page")
    filtered_data = p.get_page(page_number)

    return render(request, 'mysite/dataset_list.html', {"dataset" : filtered_data, "dataset_num": counts, "status_filter": status_filter, "active_navbar_page": "datasets"})