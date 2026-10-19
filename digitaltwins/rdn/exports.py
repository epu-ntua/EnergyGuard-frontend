"""JupyterHub export of RDN grid simulation results."""

import json

from ..models import RdnSimulationJob
from ..services.jupyterhub_export import (
    Exportable, ResultNotFound, copy_from_simulations, export_source, put_json, source_folder,
)
from .services.results import result_object_key


@export_source('rdn')
def resolve_rdn_job(user, rdn_request_id):
    job = RdnSimulationJob.objects.filter(
        rdn_request_id=rdn_request_id, user=user, status=RdnSimulationJob.Status.COMPLETED,
    ).defer('result').first()
    if job is None or not job.has_result:
        raise ResultNotFound

    name = f'rdn-grid-run-{job.rdn_request_id}'
    if job.result_key:
        return Exportable('rdn-grid', job.result_key, name, 'result.json', copy_from_simulations(job.result_key))
    # A legacy job whose payload is still inline in the database column
    # (has_result above already loaded it from the deferred column).
    return Exportable(
        'rdn-grid', result_object_key(job.rdn_request_id), name, 'result.json',
        put_json(lambda: json.dumps(job.result).encode('utf-8')),
    )


def rdn_source_prefix(rdn_request_id):
    return source_folder(result_object_key(rdn_request_id))
