import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..models import Dataset
from ..services.minio_storage import _build_minio_client


def _fetch_metadata_from_minio(dataset) -> dict | None:
    """
    Download and parse the metadata JSON file from MinIO.
    Returns the parsed dict, or None if unavailable or not parseable.
    """
    if not dataset.metadata_file:
        return None
    try:
        client = _build_minio_client()
        response = client.get_object(
            Bucket=dataset.bucket_name,
            Key=dataset.metadata_file,
        )
        raw = response["Body"].read()
        return json.loads(raw)
    except Exception:
        return None


@login_required
def dataset_details(request, dataset_id):
    try:
        dataset = Dataset.objects.get(pk=dataset_id)
    except Dataset.DoesNotExist:
        messages.error(request, "Dataset not found")
        return redirect("home")

    minio_metadata = _fetch_metadata_from_minio(dataset)

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
        "metadata": minio_metadata if minio_metadata is not None else dataset.metadata,
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
