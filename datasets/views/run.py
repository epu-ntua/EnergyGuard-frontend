import json
from django.utils.text import slugify

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

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

    if not dataset.data_file:
        return JsonResponse({"error": "This dataset has no data file."}, status=400)

    username = request.user.username
    dataset_slug = slugify(dataset.name) or f"dataset_{dataset.id}"

    if dataset.publisher_id:
        publisher_username = dataset.publisher.username
    else:
        publisher_username = "energyguard"

    payload = {
        "username": username,
        "datasets": {
            publisher_username: dataset_slug,
        },
        # "notebooks": None,
    }

    try:
        response = requests.post(
            f"{settings.DATA_MANAGEMENT_SERVER_URL}/api/v1/provision/user",
            headers={
                "X-API-Key": settings.DATA_MANAGEMENT_SERVER_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return JsonResponse(
            {"error": f"Failed to provision dataset: {exc}"},
            status=502,
        )

    user_email = request.user.email
    jupyterhub_url = settings.JUPYTERHUB_URL.rstrip("/")
    redirect_url = f"{jupyterhub_url}/user/{user_email}/lab"

    return JsonResponse({"redirect_url": redirect_url})
