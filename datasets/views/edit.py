import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from ..forms import GeneralDatasetForm
from ..models import Dataset
from ..services import MinioUploadError, delete_dataset_cache, delete_dataset_objects, provision_user_datasets
from ..services.review import EditOutcome, apply_edit

logger = logging.getLogger(__name__)


@login_required
def dataset_edit(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if not dataset.is_editable_by(request.user):
        messages.error(request, "You do not have permission to edit this dataset.")
        return redirect("dataset_details", dataset_id=dataset_id)

    if request.method != "POST":
        return redirect("dataset_details", dataset_id=dataset_id)

    old_name = dataset.name
    was_awaiting_review = dataset.is_awaiting_review
    form = GeneralDatasetForm(request.POST, instance=dataset)
    if form.is_valid():
        outcome = apply_edit(form, was_awaiting_review=was_awaiting_review)
        new_name = dataset.name
        if old_name != new_name and dataset.data_file:
            minio_prefix = "/".join(dataset.data_file.split("/")[:-1])
            try:
                delete_dataset_cache(request.user.email, old_name)
            except Exception:
                logger.exception("Could not drop JupyterHub cache of renamed dataset %s", dataset.pk)
            try:
                provision_user_datasets(request.user.email, {minio_prefix: new_name})
            except Exception:
                logger.exception("Could not re-provision renamed dataset %s in JupyterHub", dataset.pk)
        if outcome == EditOutcome.REOPENED:
            messages.success(
                request,
                "Dataset updated. Your changes have been sent for review, and the dataset is hidden "
                "from the public catalogue until a reviewer approves them.",
            )
        elif outcome == EditOutcome.SUBMITTED:
            messages.success(
                request,
                "Dataset updated and submitted for review. It will appear in the public catalogue once approved.",
            )
        elif outcome == EditOutcome.REJECTED:
            messages.warning(
                request,
                "Dataset updated. Its publication was rejected, so it remains hidden from the public "
                "catalogue and has not been sent for review again.",
            )
        else:
            messages.success(request, "Dataset updated successfully.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)

    return redirect("dataset_details", dataset_id=dataset_id)


@login_required
def dataset_delete(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if not dataset.is_editable_by(request.user):
        messages.error(request, "You do not have permission to delete this dataset.")
        return redirect("dataset_details", dataset_id=dataset_id)

    if request.method != "POST":
        return redirect("dataset_details", dataset_id=dataset_id)

    username = dataset.publisher.username
    dataset_name = dataset.name
    minio_prefix = "/".join(dataset.data_file.split("/")[:-1]) if dataset.data_file else None

    # Step 1: delete from JupyterHub cache — no compensation needed if this fails
    try:
        delete_dataset_cache(username, dataset_name)
    except Exception:
        logger.exception("Failed to delete dataset '%s' (id=%s) from JupyterHub cache", dataset_name, dataset_id)
        messages.error(request, "Dataset could not be deleted. Please try again or contact support if the issue persists.")
        return redirect("dataset_details", dataset_id=dataset_id)

    # Step 2: delete from MinIO — compensate by re-provisioning JupyterHub if this fails.
    # Delete the object at the key stored on the dataset. Rebuilding its path
    # from the username and name missed it: the folder is named after the
    # *slugified* username ("user_janedoeexamplecom") and the name at upload
    # time, so the delete reported success while the file stayed in MinIO.
    try:
        delete_dataset_objects(bucket_name=dataset.bucket_name, data_file_key=dataset.data_file)
    except MinioUploadError:
        logger.exception("Failed to delete dataset '%s' (id=%s) from MinIO storage", dataset_name, dataset_id)
        if minio_prefix:
            try:
                provision_user_datasets(username, {minio_prefix: dataset_name})
            except Exception:
                logger.error(
                    "Compensation failed: could not re-provision JupyterHub cache for dataset '%s' "
                    "(user %s) after MinIO delete failure — manual intervention required.",
                    dataset_name, username,
                )
        messages.error(request, "Dataset could not be deleted. Please try again or contact support if the issue persists.")
        return redirect("dataset_details", dataset_id=dataset_id)

    # Step 3: delete from DB — log critical if this fails since MinIO + JupyterHub are already gone
    try:
        dataset.delete()
    except Exception as e:
        logger.critical(
            "DB delete failed for dataset '%s' (id=%s, user %s) after MinIO and JupyterHub "
            "deletion succeeded — orphaned DB record requires manual cleanup: %s",
            dataset_name, dataset_id, username, e,
        )
        messages.error(request, "Dataset could not be deleted. Please try again or contact support if the issue persists.")
        return redirect("dataset_details", dataset_id=dataset_id)

    messages.success(request, f'Dataset "{dataset_name}" has been deleted.')
    return redirect(reverse("datasets_list") + "?tab=my")
