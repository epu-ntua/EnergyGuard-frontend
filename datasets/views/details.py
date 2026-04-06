from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render

from projects.models import Project
from ..forms import GeneralDatasetForm
from ..models import Dataset


@login_required
def dataset_details(request, dataset_id):
    try:
        dataset = Dataset.objects.get(pk=dataset_id)
    except Dataset.DoesNotExist:
        messages.error(request, "Dataset not found")
        return redirect("home")

    dataset_details_data = {
        "id": dataset.id,
        "name": dataset.name,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "status": dataset.status,
        "label": dataset.get_label_display(),
        "source": dataset.get_source_display(),
        "visibility": dataset.visibility,
        "size": dataset.size_gb,
        "publisher": dataset.publisher_display,
        "description": dataset.description,
        "metadata": dataset.metadata,
    }

    user_projects = Project.objects.filter(
        Q(creator=request.user) | Q(collaborators=request.user)
    ).distinct().order_by("-created_at")

    return render(
        request,
        "datasets/dataset-details.html",
        {
            "dataset": dataset,
            "dt": dataset_details_data,
            "edit_form": GeneralDatasetForm(instance=dataset),
            "user_projects": user_projects,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )
