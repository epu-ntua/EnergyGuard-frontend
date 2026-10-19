"""Copying a stored twin result into the datasets bucket, for JupyterHub.

The data-management server provisions files into JupyterHub only from the datasets
bucket (OBJECT_STORAGE_BUCKET), while the twins keep their results in
OBJECT_STORAGE_BUCKET_SIMULATIONS. The result is copied over on the server side;
the browser only names which result, so what lands in JupyterHub is what the twin
returned. Switch to provisioning from the simulations bucket directly once the
data-management server supports other buckets.

Which results can be exported is up to the twins: each registers a source with
@export_source in its own `exports` module (loaded by DigitaltwinsConfig.ready),
so this module knows nothing of any particular twin.
"""

import logging
from dataclasses import dataclass
from typing import Callable

import requests
from django.conf import settings

from core.services.object_storage import MinioUploadError, copy_object, delete_object, object_exists, put_object
from datasets.services import delete_dataset_cache

from ..common import user_storage_folder
from ..models import DtExport

logger = logging.getLogger(__name__)


class ResultNotFound(Exception):
    """No completed result of this user matches the requested source and id."""


@dataclass(frozen=True)
class Exportable:
    """One of the user's stored results, ready to be copied for JupyterHub."""

    twin_slug: str
    # The stored object it comes from; the folder holding it identifies the
    # source when its exports must go (see source_folder).
    source_key: str
    # The folder of the copy, in the user's folder and in JupyterHub - named after
    # the run as the user sees it, e.g. engreen-antrodoco-historical-run-12.
    name: str
    filename: str
    # write(bucket, key): puts the copy there.
    write: Callable[[str, str], None]


_SOURCES = {}


def export_source(name):
    """Register `resolve(user, source_id) -> Exportable` as the export source `name`,
    the "source" the browser sends. `resolve` raises ResultNotFound for a result
    that is not the user's, not finished, or has nothing stored."""
    def register(resolve):
        _SOURCES[name] = resolve
        return resolve
    return register


def is_export_source(name):
    return name in _SOURCES


def copy_from_simulations(object_key):
    """A `write` that copies a stored object inside the storage server."""
    return lambda bucket, dest: copy_object(
        source_bucket=settings.OBJECT_STORAGE_BUCKET_SIMULATIONS, source_key=object_key,
        bucket_name=bucket, object_key=dest,
    )


def put_json(get_bytes):
    """A `write` that uploads JSON produced by `get_bytes()`, called only when writing."""
    return lambda bucket, dest: put_object(
        bucket_name=bucket, object_key=dest, body=get_bytes(), content_type='application/json',
    )


def export_result(*, user, source, source_id) -> DtExport:
    """Place the user's result `source_id` of `source` in the datasets bucket.

    The copy is user_<slug>/<name>/<file>, and <name> is also its folder in
    JupyterHub. So exporting a result again lands in the same place - reusing the
    copy while it is there, rewriting it otherwise (as when BER has replaced the
    result file since).

    Raises ResultNotFound, or MinioUploadError if storage fails.
    """
    resolve = _SOURCES.get(source)
    if resolve is None:
        raise ResultNotFound
    exportable = resolve(user, source_id)

    previous = DtExport.objects.filter(user=user, source_key=exportable.source_key).order_by('-created_at').first()
    if previous and object_exists(bucket_name=previous.bucket_name, object_key=previous.result_key):
        return previous

    bucket_name = settings.OBJECT_STORAGE_BUCKET
    # A development machine prefixes its copies so they never share a name with
    # production's in the user's folder (see DT_EXPORT_NAME_PREFIX).
    name = f'{settings.DT_EXPORT_NAME_PREFIX}{exportable.name}'
    result_key = f'{user_storage_folder(user)}/{name}/{exportable.filename}'
    exportable.write(bucket_name, result_key)

    # One row per copy: the name is fixed per result, so a re-export updates it.
    export, _ = DtExport.objects.update_or_create(
        user=user, bucket_name=bucket_name, result_key=result_key,
        defaults={'twin_slug': exportable.twin_slug, 'source_key': exportable.source_key},
    )
    return export


# ── Removing the exports of a deleted result ─────────────────────────────────
#
# Each source keeps all its result files under one folder of the simulations
# bucket (a BER request gets a new file each time BER replaces its result), so
# the folder finds every export of a source, whichever of its files was exported.

def source_folder(object_key):
    return object_key.rsplit('/', 1)[0] + '/'


def remove_exports(*, user_id, source_prefix):
    """Delete the user's JupyterHub copies of one source's results. Each deleted
    DtExport cleans up its object and JupyterHub file (digitaltwins.signals)."""
    if source_prefix:
        DtExport.objects.filter(user_id=user_id, source_key__startswith=source_prefix).delete()


def discard_export(*, bucket_name, result_key, email):
    """Best-effort removal of a deleted export's copy: its datasets-bucket object
    and the file provisioned from it into JupyterHub. Failures are logged (with
    the key, for a manual clean-up) rather than raised. Runs on the qcluster."""
    try:
        delete_object(bucket_name=bucket_name, object_key=result_key)
    except MinioUploadError:
        logger.exception('Could not delete JupyterHub export %s; it is orphaned', result_key)

    if not email:
        return
    # The folder name is what the file was provisioned under (see dt_save_result).
    dataset_local_name = source_folder(result_key).rstrip('/').rsplit('/', 1)[1]
    try:
        # JupyterHub identifies users by email, as when provisioning.
        delete_dataset_cache(email, dataset_local_name)
    except requests.RequestException:
        pass  # already logged in delete_dataset_cache
