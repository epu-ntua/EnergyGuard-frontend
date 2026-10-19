"""JupyterHub export of BER experiment results."""

from ..models import BerExperimentRequest
from ..services.jupyterhub_export import (
    Exportable, ResultNotFound, copy_from_simulations, export_source, source_folder,
)
from .services.results import ber_experiment_id
from .services.storage import result_object_key


@export_source('ber')
def resolve_ber_request(user, request_id):
    experiment_request = BerExperimentRequest.objects.filter(
        pk=request_id, user=user, status=BerExperimentRequest.Status.COMPLETED,
    ).exclude(result_key='').first()
    if experiment_request is None:
        raise ResultNotFound

    # BER may replace the file; each upload has a fresh key, so a replaced result
    # is exported again rather than reusing the old copy.
    key = experiment_request.result_key
    return Exportable(
        twin_slug='ber-hydrogen',
        source_key=key,
        name=f'ber-hydrogen-request-{experiment_request.pk}',
        # Named like its download: the experiment ID and the uploaded extension.
        filename=f"{ber_experiment_id(experiment_request)}.{key.rsplit('.', 1)[-1]}",
        write=copy_from_simulations(key),
    )


def ber_source_prefix(experiment_request_id):
    return source_folder(result_object_key(experiment_request_id))
