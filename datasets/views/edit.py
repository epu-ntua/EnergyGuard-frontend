import requests
from django.conf import settings
from django.contrib import messages
from django.utils.text import slugify
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from ..forms import GeneralDatasetForm
from ..models import Dataset
from ..services import delete_dataset_cache, provision_user_datasets


@login_required
def dataset_edit(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if request.user != dataset.publisher:
        messages.error(request, "You do not have permission to edit this dataset.")
        return redirect("dataset_details", dataset_id=dataset_id)

    if request.method != "POST":
        return redirect("dataset_details", dataset_id=dataset_id)

    old_name = dataset.name
    form = GeneralDatasetForm(request.POST, instance=dataset)
    if form.is_valid():
        form.save()
        new_name = dataset.name
        if old_name != new_name and dataset.data_file:
            minio_prefix = "/".join(dataset.data_file.split("/")[:-1])
            try:
                delete_dataset_cache(request.user.email, old_name)
            except Exception:
                pass
            try:
                provision_user_datasets(request.user.email, {minio_prefix: new_name})
            except Exception:
                pass
        messages.success(request, "Dataset updated successfully.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)

    return redirect("dataset_details", dataset_id=dataset_id)


@login_required
def dataset_delete(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if request.user != dataset.publisher:
        messages.error(request, "You do not have permission to delete this dataset.")
        return redirect("dataset_details", dataset_id=dataset_id)

    if request.method != "POST":
        return redirect("dataset_details", dataset_id=dataset_id)

    username = dataset.publisher.username
    dataset_name = dataset.name
    dataset_slug = slugify(dataset_name)

    url = f"{settings.DATA_MANAGEMENT_SERVER_URL}/api/v1/datasets/{username}/{dataset_slug}"
    try:
        response = requests.delete(
            url,
            headers={"X-API-Key": settings.DATA_MANAGEMENT_SERVER_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        messages.error(request, f'Failed to delete dataset from data management server: {e}')
        return redirect("dataset_details", dataset_id=dataset_id)

    dataset.delete()
    messages.success(request, f'Dataset "{dataset_name}" has been deleted.')
    return redirect(reverse("datasets_list") + "?tab=my")
