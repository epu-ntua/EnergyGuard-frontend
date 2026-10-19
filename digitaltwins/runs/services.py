"""Recording and reading the runs of the twins that answer straight away.

Each completed run's result is stored gzipped in OBJECT_STORAGE_BUCKET_SIMULATIONS:
these results are time series in JSON, which compress several times over. A result
larger than MAX_RESULT_BYTES (uncompressed) is not stored; the run is still listed,
as NOT_KEPT, so the history shows it happened.

Recording never breaks the run itself: the user already has the answer on screen,
so a storage or database failure is logged and the run is simply not kept.

Deleting a run, by any path, removes its stored result and JupyterHub copies
(digitaltwins.signals).
"""

import gzip
import json
import logging
import uuid

from django.conf import settings
from django.utils import timezone

from core.services.object_storage import MinioUploadError, delete_object, open_object_stream, put_object

from ..common import user_storage_folder
from ..models import DtRun

logger = logging.getLogger(__name__)

MAX_RESULT_BYTES = 20 * 1024 * 1024

# Level 6 (zlib's default) compresses JSON nearly as well as gzip.compress's
# default 9, in a fraction of the time - and this runs inside the user's request.
_GZIP_LEVEL = 6

# Response header carrying the recorded run's id, kept apart from the service's own
# payload so a field of the service can never collide with it.
RUN_ID_HEADER = 'X-DT-Run-Id'


def result_object_key(user, twin_slug):
    """dt-runs/<twin>/user_<slug>/<when>-<random>/result.json.gz

    Grouped by twin and user, so one user's runs can be found (and sized) in
    storage. Fresh and independent of the row, since the result is stored before
    the row is written: the run's id does not exist yet, hence the random part.
    Each run has its own folder, which is how its JupyterHub copies are found
    (jupyterhub_export).
    """
    folder = f'{timezone.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}'
    return f'dt-runs/{twin_slug}/{user_storage_folder(user)}/{folder}/result.json.gz'


def record_run(*, user, twin_slug, operation, inputs, result=None, error=''):
    """Record a run whose service answered with `result`, or failed with `error`.

    Returns the DtRun, or None if not even the row could be written.
    """
    fields = {'user': user, 'twin_slug': twin_slug, 'operation': operation, 'inputs': inputs}

    if error:
        return _create(DtRun.Status.FAILED, error_message=error, **fields)

    body = json.dumps(result).encode('utf-8')
    if len(body) > MAX_RESULT_BYTES:
        logger.warning('Not keeping %s %s run of user %s: result is %d bytes (limit %d)',
                       twin_slug, operation, user.pk, len(body), MAX_RESULT_BYTES)
        return _create(DtRun.Status.NOT_KEPT, error_message='The result was too large to keep.', **fields)

    object_key = result_object_key(user, twin_slug)
    try:
        put_object(
            bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS,
            object_key=object_key,
            body=gzip.compress(body, compresslevel=_GZIP_LEVEL),
            content_type='application/json',
        )
    except MinioUploadError:
        logger.exception('Could not store the result of a %s %s run of user %s', twin_slug, operation, user.pk)
        return _create(DtRun.Status.NOT_KEPT, error_message='The result could not be stored.', **fields)

    run = _create(DtRun.Status.COMPLETED, result_key=object_key, **fields)
    if run is None:
        # The file has no row pointing at it any more; remove it rather than orphan it.
        discard_run_result(object_key)
    return run


def _create(status, **fields):
    try:
        return DtRun.objects.create(status=status, **fields)
    except Exception:
        logger.exception('Could not record %s %s run for user %s',
                         fields['twin_slug'], fields['operation'], fields['user'].pk)
        return None


def discard_run_result(object_key):
    """Best-effort removal of a result no row points to any more. A failure only
    leaves an orphaned object, so it is logged (with the key) rather than raised."""
    try:
        delete_object(bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, object_key=object_key)
    except MinioUploadError:
        logger.exception('Could not delete DT run result %s; it is orphaned', object_key)


def attach_run_id(response, run):
    """Tell the page which stored run it is showing, so it can reopen or export it.
    Left off when the result was not kept: there is nothing on the server to point at."""
    if run is not None and run.has_result:
        response[RUN_ID_HEADER] = str(run.pk)
    return response


def open_run_result(run):
    """Return (gzipped body, content_length) of a run's stored result; the caller closes body.

    Raises MinioUploadError if it cannot be read.
    """
    return open_object_stream(bucket_name=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, object_key=run.result_key)


def read_run_result_bytes(run):
    """The run's result as uncompressed JSON bytes. Raises MinioUploadError if unreadable."""
    body, _ = open_run_result(run)
    try:
        return gzip.decompress(body.read())
    finally:
        body.close()
