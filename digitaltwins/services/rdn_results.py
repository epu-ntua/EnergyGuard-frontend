"""Storage for completed RDN grid simulation results.

An RDN result is bounded only by `_RDN_MAX_OUTPUT_SAMPLES` (4,000,000 samples),
so keeping it in a Postgres JSONB column meant rows of hundreds of megabytes,
TOAST pressure, backups that grow without limit, and a status-polling endpoint
that re-serialised the whole payload on every poll after completion.

Results now live in object storage; the row keeps only the key. Jobs completed
before this change still carry their payload in `RdnSimulationJob.result`, so
every read goes through `load_result`, which falls back to that column.
"""

import json
import logging

from django.conf import settings

from core.services.object_storage import (
    MinioUploadError,
    build_minio_client,
    put_object,
)

logger = logging.getLogger(__name__)

RESULT_CONTENT_TYPE = "application/json"


def result_object_key(rdn_request_id) -> str:
    return f"rdn-grid/{rdn_request_id}/result.json"


def store_result(rdn_request_id, result) -> str | None:
    """Write a completed result to object storage.

    Returns the object key, or None if the upload failed - in which case the
    caller keeps the payload in the database rather than losing an hour-long run.
    """
    object_key = result_object_key(rdn_request_id)
    try:
        put_object(
            bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS,
            object_key=object_key,
            body=json.dumps(result).encode("utf-8"),
            content_type=RESULT_CONTENT_TYPE,
        )
    except MinioUploadError:
        logger.exception(
            "Could not store RDN result for request %s in object storage; "
            "falling back to the database column.",
            rdn_request_id,
        )
        return None
    return object_key


def open_result_stream(object_key):
    """Return the stored result's raw body, for streaming straight to the client.

    Raises MinioUploadError if the object cannot be read.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    client = build_minio_client()
    try:
        response = client.get_object(
            Bucket=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, Key=object_key
        )
    except (ClientError, BotoCoreError) as exc:
        raise MinioUploadError(str(exc)) from exc
    return response["Body"], response.get("ContentLength")


def load_result(job):
    """The job's result as a dict, from object storage or the legacy column.

    Only for callers that genuinely need the parsed payload in Python - serving
    it to a browser should stream via `open_result_stream` instead of paying to
    parse and re-serialise it.
    """
    if job.result_key:
        try:
            body, _ = open_result_stream(job.result_key)
            return json.loads(body.read().decode("utf-8"))
        except (MinioUploadError, ValueError):
            logger.exception("Could not read stored RDN result %s", job.result_key)
            return None
    return job.result
