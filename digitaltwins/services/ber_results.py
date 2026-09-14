"""Storage for BER-uploaded experiment result files.

BER staff upload the raw result file (.lp) for a specific request through the
management page - an explicit per-request upload, not timestamp-based retrieval
from the Data Lake. The row keeps only the object key, mirroring rdn_results.py.
"""

from django.conf import settings

from core.services.object_storage import put_object


def result_object_key(experiment_request_id, filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'lp'
    return f'ber-hydrogen/{experiment_request_id}/result.{ext}'


def store_result_file(experiment_request_id, uploaded_file):
    """Upload the BER-provided result file to object storage. Returns the object key.

    Raises MinioUploadError on failure - unlike RDN's store_result, there is no
    database fallback here since the raw file has nowhere else to live.
    """
    object_key = result_object_key(experiment_request_id, uploaded_file.name)
    put_object(
        bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS,
        object_key=object_key,
        body=uploaded_file.read(),
        content_type=uploaded_file.content_type or 'application/octet-stream',
    )
    return object_key
