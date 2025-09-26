from django.core.paginator import Paginator
from django.shortcuts import render 
from datetime import datetime
import mlflow

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

    return render(request, 'mysite/experiments_list.html', {"experiments" : filtered_data, "experiments_num": counts})