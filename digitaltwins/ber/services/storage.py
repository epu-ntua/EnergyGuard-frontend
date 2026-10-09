"""Storage for BER-uploaded experiment result files.

BER staff upload the raw result file (.lp) for a specific request through the
management page - an explicit per-request upload, not timestamp-based retrieval
from the Data Lake. The row keeps only the object key, mirroring rdn_results.py.
"""

from datetime import datetime, timezone

from django.conf import settings

from core.services.object_storage import delete_object, open_object_stream, upload_fileobj


def result_object_key(experiment_request_id):
    """A fresh key per upload, so replacing a result never overwrites the file the
    request currently points to (the old one is deleted only after the switch).

    Always `.lp`: uploads are checked to be line protocol before they are stored,
    and the extension ends up in the download's Content-Disposition, so it must
    not come from the uploaded file's name.
    """
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    return f'ber-hydrogen/{experiment_request_id}/result-{stamp}.lp'


def store_result_file(experiment_request_id, uploaded_file, progress_callback=None):
    """Upload the BER-provided result file to object storage. Returns the object key.

    Raises MinioUploadError on failure - unlike RDN's store_result, there is no
    database fallback here since the raw file has nowhere else to live.
    `progress_callback(bytes_sent)` is forwarded to the upload (see upload_fileobj).
    """
    object_key = result_object_key(experiment_request_id)
    upload_fileobj(
        bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS,
        object_key=object_key,
        fileobj=uploaded_file,
        # Not the browser-supplied type: it is client-controlled and the file is
        # only ever served as a download.
        content_type='application/octet-stream',
        callback=progress_callback,
    )
    return object_key


def open_result_file(object_key):
    """Return (body, content_length) of a stored result file; the caller closes body.

    Raises MinioUploadError if it cannot be read.
    """
    return open_object_stream(bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, object_key=object_key)


def delete_result_file(object_key):
    """Remove a result file from object storage. Raises MinioUploadError on failure."""
    delete_object(bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, object_key=object_key)
