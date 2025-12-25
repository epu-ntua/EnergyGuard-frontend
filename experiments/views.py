from django.shortcuts import render, redirect
from django.db.models import Q
from .models import Experiment
from django.http import JsonResponse

# Create your views here.
def experiments_list(request):
    """mlflow.set_tracking_uri("https://mlflow.toolbox.epu.ntua.gr/")
    
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
    filtered_data = p.get_page(page_number)"""

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("draw"):
        draw = int(request.GET.get("draw", 1))
        start = int(request.GET.get("start", 0))
        length = int(request.GET.get("length", 10))
        search_value = request.GET.get("search[value]", "")
        status_filter = request.GET.get("status")

        order_col = request.GET.get("order[0][column]", "2")
        order_dir = request.GET.get("order[0][dir]", "desc")
        column_map = {
            "1": "name",
            "2": "collaborators__first_name",
            "3": "created_at",
            "4": "updated_at",
            "5": "status",
            "6": "type",
            "7": "progress",
            "8": "status"
        }
        ordering = column_map.get(order_col, "created_at")
        if order_dir == "desc":
            ordering = f"-{ordering}"

        qs = Experiment.objects.select_related("creator").prefetch_related("collaborators").all()
        if status_filter in ["completed", "ongoing", "cancelled", "inactive"]:
            qs = qs.filter(status=status_filter)

        records_total = qs.count()

        if search_value:
            qs = qs.filter(
                Q(name__icontains=search_value)
            ).distinct()

        records_filtered = qs.count()
        qs = qs.order_by(ordering)[start:start + length]

        data = []
        for exp in qs:
            data.append({
                "id": exp.id,
                "name": exp.name,
                "description": exp.description,
                "collaborators": ", ".join(exp.collaborators.values_list("first_name", flat=True)),
                "created_at": exp.created_at.strftime("%b %d, %Y"),
                "updated_at": exp.updated_at.strftime("%b %d, %Y"),
                "type": exp.get_exp_type_display(),
                "progress": exp.progress,
                "status": exp.status,
                "status_badge": exp.status,
            })

        return JsonResponse({
            "draw": draw,
            "recordsTotal": records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        })
    data = Experiment.objects.all()
    counts = {
        "all": data.count(),
        "completed": data.filter(status="completed").count(),
        "ongoing": data.filter(status="ongoing").count(),
        "cancelled": data.filter(status="cancelled").count(),
        "inactive": data.filter(status="inactive").count(),
    }
    status_filter = request.GET.get("status")
    return render(request, 'mysite/experiments-list.html', {
        "experiment" : data, 
        "experiments_num": counts, 
        "status_filter": status_filter, 
        "active_navbar_page": "experiments", 
        "show_vertical_navbar": True
    })

def experiments_list_tabs(request):

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("draw"):
        draw = int(request.GET.get("draw", 1))
        start = int(request.GET.get("start", 0))
        length = int(request.GET.get("length", 10))
        search_value = request.GET.get("search[value]", "")
        status_filter = request.GET.get("status")
        visibility_filter = request.GET.get("visibility", "false")

        order_col = request.GET.get("order[0][column]", "2")
        order_dir = request.GET.get("order[0][dir]", "desc")
        column_map = {
            "1": "name",
            "2": "collaborators__first_name",
            "3": "created_at",
            "4": "updated_at",
            "5": "status",
            "6": "type",
            "7": "progress",
            "8": "status"
        }
        ordering = column_map.get(order_col, "created_at")
        if order_dir == "desc":
            ordering = f"-{ordering}"

        qs = Experiment.objects.select_related("creator").prefetch_related("collaborators").filter(visibility = visibility_filter=="true")
        if status_filter in ["completed", "ongoing", "cancelled", "inactive"]:
            qs = qs.filter(status=status_filter)

        records_total = qs.count()

        if search_value:
            qs = qs.filter(
                Q(name__icontains=search_value)
            ).distinct()

        records_filtered = qs.count()
        qs = qs.order_by(ordering)[start:start + length]

        data = []
        for exp in qs:
            data.append({
                "id": exp.id,
                "name": exp.name,
                "description": exp.description,
                "collaborators": ", ".join(exp.collaborators.values_list("first_name", flat=True)),
                "created_at": exp.created_at.strftime("%b %d, %Y"),
                "updated_at": exp.updated_at.strftime("%b %d, %Y"),
                "type": exp.get_exp_type_display(),
                "progress": exp.progress,
                "status": exp.status,
            })

        return JsonResponse({
            "draw": draw,
            "recordsTotal": records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        })
    visibility_filter = request.GET.get("visibility", "false")
    data = Experiment.objects.filter(visibility=visibility_filter=="true")
    counts = {
        "all": data.count(),
        "completed": data.filter(status="completed").count(),
        "ongoing": data.filter(status="ongoing").count(),
        "cancelled": data.filter(status="cancelled").count(),
        "inactive": data.filter(status="inactive").count(),
    }
    status_filter = request.GET.get("status")
    return render(request, 'mysite/experiments-list-tabs-test.html', {
        "experiment" : data, 
        "experiments_num": counts, 
        "status_filter": status_filter, 
        "active_navbar_page": "experiments", 
        "show_vertical_navbar": True,
        "visibility_filter": visibility_filter
    })

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
            "visibility": experiment.visibility,
            "company": experiment.creator.profile.company if hasattr(experiment.creator, 'profile') else None
        }
    except Experiment.DoesNotExist:
        return redirect('error_does_not_exist', error= "Experiment not found")  # or render an error page
    
    return render(request, 'mysite/experiment-details.html', {"experiment": experiment, "exp": experiment_details,  "active_navbar_page": "experiments", "show_vertical_navbar": True})
