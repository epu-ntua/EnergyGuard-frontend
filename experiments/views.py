from django.shortcuts import render, redirect
from django.db.models import Q
from .models import Experiment
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django_datatables_view.base_datatable_view import BaseDatatableView
from core.views import BaseWizardView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from .forms import *

class ExperimentsListJson(BaseDatatableView):
    model = Experiment
    columns = [
        "name",
        "description",
        "collaborators",
        "created_at",
        "updated_at",
        "exp_type",
        # "progress",
        # "status",
        "id",
    ]
    order_columns = [
        "name",
        "description",
        "collaborators__first_name",
        "created_at",
        "updated_at",
        "exp_type",
        # "progress",
        # "status",
    ]
    max_display_length = 25

    def get_initial_queryset(self):
        # Prefetch related collaborators to optimize DB queries
        return Experiment.objects.prefetch_related("collaborators").all()
    
    def render_column(self, row, column):
        if column == "created_at":
            return row.created_at.strftime("%b %d, %Y")
        elif column == "updated_at":
            return row.updated_at.strftime("%b %d, %Y")
        elif column == "collaborators":
            return ", ".join(user.first_name for user in row.collaborators.all()) or "No collaborators"
        elif column == "exp_type":
            return row.get_exp_type_display()
        else:
            return super().render_column(row, column)
        
    def filter_queryset(self, qs):
        # Apply custom filtering based on request parameters
        search = self.request.GET.get("search[value]", None)
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            ).distinct()
        
        type_filter = self.request.GET.get("type")
        if type_filter in ["ai_model", "ai_service", "web_app", "mobile_app", "iot_integration", "data_pipeline"]:
            qs = qs.filter(exp_type=type_filter)    
        return qs

@login_required
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

    qs = Experiment.objects.all()
    counts = {
        "all": qs.count(),
        "ai_model": qs.filter(exp_type="ai_model").count(),
        "ai_service": qs.filter(exp_type="ai_service").count(),
        "web_app": qs.filter(exp_type="web_app").count(),
        "mobile_app": qs.filter(exp_type="mobile_app").count(),
        "iot_integration": qs.filter(exp_type="iot_integration").count(),
        "data_pipeline": qs.filter(exp_type="data_pipeline").count(),
    }
    type_filter = request.GET.get("type")
    return render(request, 'experiments/experiments-list.html', {
        "experiments_num": counts, 
        "type_filter": type_filter, 
        "active_navbar_page": "experiments",
        "show_sidebar": True
    })

@login_required
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
    return render(request, 'experiments/experiments-list-tabs-test.html', {
        "experiment" : data, 
        "experiments_num": counts, 
        "status_filter": status_filter, 
        "active_navbar_page": "experiments", 
        "show_sidebar": True,
        "visibility_filter": visibility_filter
    })

@login_required
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
        # return redirect('core/error_does_not_exist', error= "Experiment not found")  # or render an error page
        messages.error(request, "Experiment not found")
        return redirect('home') 

    return render(request, 'experiments/experiment-details.html', {"experiment": experiment, "exp": experiment_details,  "active_navbar_page": "experiments", "show_sidebar": True})

@login_required
def experiment_index(request):
    return render(request, 'experiments/experiment-index.html', {"active_navbar_page": "experiments", "show_sidebar": True})

EXPERIMENT_TEMPLATE_NAMES= {
    "0": "experiments/experiment-creation-step1.html", 
    "1":"experiments/experiment-creation-step2.html", 
    "2": "experiments/experiment-creation-step3.html"} 

EXPERIMENT_FORMS = [
    ("0", ExperimentGeneralInfoForm),
    ("1", ExperimentFacilitiesForm), 
    ("2", ExperimentSandboxPackagesForm) 
]

EXPERIMENT_STEP_METADATA = { 
    "0": {"title": "General", 'icon': 'fa-info-circle'}, 
    "1": {"title": "Facilities", "icon": 'fa-building'}, 
    "2": {"title": "Packages", "icon": 'fa-cubes-stacked'} }

class AddExperimentView(LoginRequiredMixin, BaseWizardView):
    template_names = EXPERIMENT_TEMPLATE_NAMES
    step_metadata = EXPERIMENT_STEP_METADATA

    def done(self, form_list, **kwargs):
        # Process and save experiment after all steps are completed

        general_info = form_list[0].cleaned_data
        facilities = form_list[1].cleaned_data
        sandbox_packages = form_list[2].cleaned_data

        with transaction.atomic(): 
            experiment = Experiment.objects.create( 
                name=general_info['name'], 
                description=general_info['description'], 
                exp_type=general_info['exp_type'], 
                creator=self.request.user, 
                # visibility=general_info['visibility'] 
            )
        
        return redirect('experiment_upload_success')
    
@login_required
def experiment_creation_success(request): 
    wizard = {"steps": {"current": "done"}}
    wizard_steps = EXPERIMENT_STEP_METADATA.values()
    return render(request, 'experiments/experiment-creation-success.html', {"wizard": wizard, "wizard_steps": wizard_steps})