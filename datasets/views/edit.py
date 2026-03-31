from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from ..forms import GeneralDatasetForm
from ..models import Dataset


@login_required
def dataset_edit(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if request.user != dataset.publisher:
        messages.error(request, "You do not have permission to edit this dataset.")
        return redirect("dataset_details", dataset_id=dataset_id)

    if request.method != "POST":
        return redirect("dataset_details", dataset_id=dataset_id)

    form = GeneralDatasetForm(request.POST, instance=dataset)
    if form.is_valid():
        form.save()
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

    dataset.delete()
    messages.success(request, f'Dataset "{dataset.name}" has been deleted.')
    return redirect(reverse("datasets_list") + "?tab=my")
