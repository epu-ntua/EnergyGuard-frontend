from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Dataset, DatasetUserDownload


@login_required
def dataset_details(request, dataset_id):
    try:
        dataset = Dataset.objects.prefetch_related("users").get(pk=dataset_id)
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
        "collaborators": ", ".join(user.username for user in dataset.users.all()),
        "downloaded": DatasetUserDownload.objects.filter(
            user=request.user, dataset=dataset
        ).exists(),
    }

    return render(
        request,
        "datasets/dataset-details.html",
        {
            "dataset": dataset,
            "dt": dataset_details_data,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )


@login_required
def dataset_download(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if request.user.credits < 100:
        messages.error(request, "Insufficient credits to download the dataset.")
        return redirect("dataset_details", dataset_id=dataset.id)

    Dataset.objects.filter(pk=dataset.id).update(downloads=F("downloads") + 1)
    DatasetUserDownload.objects.create(user=request.user, dataset=dataset)

    request.user.credits = F("credits") - 100
    request.user.save()

    messages.success(request, f"You have successfully downloaded the dataset: {dataset.name}")
    return redirect("dataset_details", dataset_id=dataset.id)
