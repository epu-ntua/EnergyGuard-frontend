import json

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from projects.models import Project
from projects.services import provision_user_datasets
from ..models import Dataset


@login_required
@require_POST
def dataset_run(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    try:
        body = json.loads(request.body)
        project_id = body.get("project_id")
    except (ValueError, KeyError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    if not project_id:
        return JsonResponse({"error": "project_id is required."}, status=400)

    project = get_object_or_404(Project, pk=project_id)

    if not dataset.data_file:
        return JsonResponse({"error": "This dataset has no data file."}, status=400)

    # JupyterHub identifies users by email (OAuth), so the provision server
    # must use the email as the username to land files in the right directory.
    jupyterhub_username = request.user.email
    dataset_local_name = dataset.name or f"dataset_{dataset.id}"

    # data_file is stored as "user_<owner>/<dataset_name>/<filename>".
    # The provision server expects the key in the form "user_<owner>/<dataset_name>".
    minio_prefix = "/".join(dataset.data_file.split("/")[:-1])

    try:
        provision_user_datasets(jupyterhub_username, {minio_prefix: dataset_local_name})
    except requests.RequestException as exc:
        return JsonResponse({"error": f"Failed to provision dataset: {exc}"}, status=502)

    dataset.projects.add(project)

    jupyterhub_url = settings.JUPYTERHUB_URL.rstrip("/")
    redirect_url = f"{jupyterhub_url}/user/{jupyterhub_username}/lab"

    return JsonResponse({"redirect_url": redirect_url})
