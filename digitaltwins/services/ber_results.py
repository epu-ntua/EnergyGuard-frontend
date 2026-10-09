"""Storage for BER-uploaded experiment result files.

BER staff upload the raw result file (.lp) for a specific request through the
management page - an explicit per-request upload, not timestamp-based retrieval
from the Data Lake. The row keeps only the object key, mirroring rdn_results.py.
"""

from datetime import datetime, timezone

from django.conf import settings

from core.services.object_storage import delete_object, upload_fileobj


def result_object_key(experiment_request_id, filename):
    """A fresh key per upload, so replacing a result never overwrites the file the
    request currently points to (the old one is deleted only after the switch)."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'lp'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    return f'ber-hydrogen/{experiment_request_id}/result-{stamp}.{ext}'


def store_result_file(experiment_request_id, uploaded_file, progress_callback=None):
    """Upload the BER-provided result file to object storage. Returns the object key.

    Raises MinioUploadError on failure - unlike RDN's store_result, there is no
    database fallback here since the raw file has nowhere else to live.
    `progress_callback(bytes_sent)` is forwarded to the upload (see upload_fileobj).
    """
    object_key = result_object_key(experiment_request_id, uploaded_file.name)
    upload_fileobj(
        bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS,
        object_key=object_key,
        fileobj=uploaded_file,
        content_type=uploaded_file.content_type or 'application/octet-stream',
        callback=progress_callback,
    )
    return object_key


def delete_result_file(object_key):
    """Remove a result file from object storage. Raises MinioUploadError on failure."""
    delete_object(bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, object_key=object_key)
