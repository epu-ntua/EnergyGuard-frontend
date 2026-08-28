import logging
import os

from botocore.exceptions import BotoCoreError, ClientError
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseServerError, StreamingHttpResponse
from django.shortcuts import get_object_or_404

from core.services.object_storage import MinioUploadError, build_minio_client

from ..models import Dataset

logger = logging.getLogger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


@login_required
def dataset_download(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if not dataset.data_file:
        raise Http404("No data file available for this dataset.")

    try:
        client = build_minio_client()
        s3_response = client.get_object(Bucket=dataset.bucket_name, Key=dataset.data_file)
    except ClientError as exc:
        # A Dataset row can outlive its object: a pilot export that has not run
        # yet, or a file removed behind the platform's back.
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
            logger.warning(
                "Dataset %s points at missing object %s/%s",
                dataset_id, dataset.bucket_name, dataset.data_file,
            )
            raise Http404("This dataset is not available yet.") from exc
        logger.error("Storage error retrieving dataset %s: %s", dataset_id, exc)
        return HttpResponseServerError("File could not be retrieved. Please try again.")
    except (BotoCoreError, MinioUploadError) as exc:
        logger.error("Storage error retrieving dataset %s: %s", dataset_id, exc)
        return HttpResponseServerError("File could not be retrieved. Please try again.")

    filename = os.path.basename(dataset.data_file)
    content_type = s3_response.get("ContentType", "application/octet-stream")
    if filename.endswith(".gz"):
        content_type = "application/gzip"
    content_length = s3_response.get("ContentLength")

    def _stream():
        body = s3_response["Body"]
        while True:
            chunk = body.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk

    response = StreamingHttpResponse(_stream(), content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    if content_length is not None:
        response["Content-Length"] = content_length
    return response
