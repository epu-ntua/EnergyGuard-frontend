import json
import uuid

from django.conf import settings
from django.utils.text import slugify

from core.services.object_storage import put_object

from ..models import DtResult


def save_simulation_result(*, twin_slug: str, user, data: dict) -> DtResult:
    """Upload a simulation result as JSON to MinIO and record it against the user.

    Stored in the datasets bucket (not OBJECT_STORAGE_BUCKET_SIMULATIONS /
    "dt-results") because the data-management server that provisions files
    into JupyterHub only reads from the datasets bucket today. Switch
    bucket_name back to OBJECT_STORAGE_BUCKET_SIMULATIONS once it supports
    provisioning from other buckets.
    """
    bucket_name = settings.OBJECT_STORAGE_BUCKET
    user_slug = slugify(user.username or str(user.pk)) or "user"
    dataset_local_name = f"{twin_slug}-result-{uuid.uuid4().hex[:8]}"
    result_key = f"user_{user_slug}/{dataset_local_name}/result.json"

    put_object(
        bucket_name=bucket_name,
        object_key=result_key,
        body=json.dumps(data).encode("utf-8"),
        content_type="application/json",
    )

    return DtResult.objects.create(
        twin_slug=twin_slug,
        user=user,
        bucket_name=bucket_name,
        result_key=result_key,
    )
