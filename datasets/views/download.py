import os

from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404

from ..models import Dataset
from ..services.minio_storage import MinioUploadError, _build_minio_client

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


@login_required
def dataset_download(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if not dataset.data_file:
        from django.http import Http404
        raise Http404("No data file available for this dataset.")

    try:
        client = _build_minio_client()
        s3_response = client.get_object(Bucket=dataset.bucket_name, Key=dataset.data_file)
    except MinioUploadError as exc:
        from django.http import HttpResponseServerError
        return HttpResponseServerError(f"Storage error: {exc}")

    filename = os.path.basename(dataset.data_file)
    content_type = s3_response.get("ContentType", "application/octet-stream")
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
