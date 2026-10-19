"""Copying a stored twin result into the datasets bucket, for JupyterHub.

The data-management server provisions files into JupyterHub only from the datasets
bucket (OBJECT_STORAGE_BUCKET), while the twins keep their results in
OBJECT_STORAGE_BUCKET_SIMULATIONS. The result is copied over on the server side;
the browser only names which result, so what lands in JupyterHub is what the twin
returned. Switch to provisioning from the simulations bucket directly once the
data-management server supports other buckets.
"""

import json
import logging

import requests
from django.conf import settings

from core.services.object_storage import MinioUploadError, copy_object, delete_object, object_exists, put_object
from datasets.services import delete_dataset_cache

from ..ber.services.results import ber_experiment_id
from ..ber.services.storage import result_object_key as ber_result_object_key
from ..common import user_storage_folder
from ..models import BerExperimentRequest, DtResult, DtRun, RdnSimulationJob
from ..rdn.services.results import result_object_key as rdn_result_object_key
from ..runs.services import read_run_result_bytes

logger = logging.getLogger(__name__)

# What the browser may name as the result to export.
SOURCES = ('run', 'rdn', 'ber')


class ResultNotFound(Exception):
    """No completed result of this user matches the requested source and id."""


def export_result(*, user, source, source_id) -> DtResult:
    """Place the user's result `source_id` of `source` in the datasets bucket.

    The copy is user_<slug>/<name>/<file>, and <name> is also its folder in
    JupyterHub: named after the run as the user sees it in "My runs", e.g.
    engreen-antrodoco-historical-run-12. So exporting a result again lands in
    the same place - reusing the copy while it is there, rewriting it otherwise
    (as when BER has replaced the result file since).

    Raises ResultNotFound, or MinioUploadError if storage fails.
    """
    twin_slug, source_key, name, filename, write = _resolve(user, source, source_id)

    previous = DtResult.objects.filter(user=user, source_key=source_key).order_by('-created_at').first()
    if previous and object_exists(bucket_name=previous.bucket_name, object_key=previous.result_key):
        return previous

    bucket_name = settings.OBJECT_STORAGE_BUCKET
    # A development machine prefixes its copies so they never share a name with
    # production's in the user's folder (see DT_EXPORT_NAME_PREFIX).
    name = f'{settings.DT_EXPORT_NAME_PREFIX}{name}'
    result_key = f'{user_storage_folder(user)}/{name}/{filename}'
    write(bucket_name, result_key)

    # One row per copy: the name is fixed per result, so a re-export updates it.
    dt_result, _ = DtResult.objects.update_or_create(
        user=user, bucket_name=bucket_name, result_key=result_key,
        defaults={'twin_slug': twin_slug, 'source_key': source_key},
    )
    return dt_result


def _resolve(user, source, source_id):
    """(twin_slug, source_key, name, file name, write(bucket, key)) for one of the
    user's results; `name` is the folder of its copy, in the bucket and in JupyterHub."""
    simulations = settings.OBJECT_STORAGE_BUCKET_SIMULATIONS

    def copy_from(key):
        return lambda bucket, dest: copy_object(
            source_bucket=simulations, source_key=key, bucket_name=bucket, object_key=dest,
        )

    def put_json(get_bytes):
        return lambda bucket, dest: put_object(
            bucket_name=bucket, object_key=dest, body=get_bytes(), content_type='application/json',
        )

    if source == 'run':
        run = DtRun.objects.filter(
            pk=source_id, user=user, status=DtRun.Status.COMPLETED,
        ).exclude(result_key='').first()
        if run is None:
            raise ResultNotFound
        name = f'{run.twin_slug}-{run.operation}-run-{run.pk}'
        # Stored gzipped; JupyterHub gets plain JSON.
        return run.twin_slug, run.result_key, name, 'result.json', put_json(lambda: read_run_result_bytes(run))

    if source == 'rdn':
        job = RdnSimulationJob.objects.filter(
            rdn_request_id=source_id, user=user, status=RdnSimulationJob.Status.COMPLETED,
        ).defer('result').first()
        if job is None or not job.has_result:
            raise ResultNotFound
        name = f'rdn-grid-run-{job.rdn_request_id}'
        if job.result_key:
            return 'rdn-grid', job.result_key, name, 'result.json', copy_from(job.result_key)
        # A legacy job whose payload is still inline in the database column
        # (has_result above already loaded it from the deferred column.)
        legacy_key = rdn_result_object_key(job.rdn_request_id)
        return 'rdn-grid', legacy_key, name, 'result.json', put_json(lambda: json.dumps(job.result).encode('utf-8'))

    if source == 'ber':
        experiment_request = BerExperimentRequest.objects.filter(
            pk=source_id, user=user, status=BerExperimentRequest.Status.COMPLETED,
        ).exclude(result_key='').first()
        if experiment_request is None:
            raise ResultNotFound
        # BER may replace the file; each upload has a fresh key, so a replaced
        # result is exported again rather than reusing the old copy.
        key = experiment_request.result_key
        name = f'ber-hydrogen-request-{experiment_request.pk}'
        # The file is named like its download: the experiment ID and the uploaded extension.
        filename = f"{ber_experiment_id(experiment_request)}.{key.rsplit('.', 1)[-1]}"
        return 'ber-hydrogen', key, name, filename, copy_from(key)

    raise ResultNotFound


# ── Removing the exports of a deleted result ─────────────────────────────────
#
# Each source keeps all its result files under one folder of the simulations
# bucket (a BER request gets a new file each time BER replaces its result), so
# the folder finds every export of a source, whichever of its files was exported.

def _folder(object_key):
    return object_key.rsplit('/', 1)[0] + '/'


def run_source_prefix(run):
    """'' for a run without a stored result: nothing of it can have been exported."""
    return _folder(run.result_key) if run.result_key else ''


def rdn_source_prefix(rdn_request_id):
    return _folder(rdn_result_object_key(rdn_request_id))


def ber_source_prefix(experiment_request_id):
    return _folder(ber_result_object_key(experiment_request_id))


def remove_exports(*, user_id, source_prefix):
    """Delete the user's JupyterHub copies of one source's results. Each deleted
    DtResult cleans up its object and JupyterHub file (digitaltwins.signals)."""
    if source_prefix:
        DtResult.objects.filter(user_id=user_id, source_key__startswith=source_prefix).delete()


def discard_export(*, bucket_name, result_key, email):
    """Best-effort removal of a deleted export's copy: its datasets-bucket object
    and the file provisioned from it into JupyterHub. Failures are logged (with
    the key, for a manual clean-up) rather than raised."""
    try:
        delete_object(bucket_name=bucket_name, object_key=result_key)
    except MinioUploadError:
        logger.exception('Could not delete JupyterHub export %s; it is orphaned', result_key)

    if not email:
        return
    # The folder name is what the file was provisioned under (see dt_save_result).
    dataset_local_name = _folder(result_key).rstrip('/').rsplit('/', 1)[1]
    try:
        # JupyterHub identifies users by email, as when provisioning.
        delete_dataset_cache(email, dataset_local_name)
    except requests.RequestException:
        pass  # already logged in delete_dataset_cache
