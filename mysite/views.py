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

    p = Paginator(data, 5)
    page_number = request.GET.get("page")
    data = p.get_page(page_number)

    return render(request, 'mysite/experiments_list.html', {"experiments" : data})