"""JupyterHub export of the runs of the twins that answer straight away (DtRun)."""

from ..models import DtRun
from ..services.jupyterhub_export import Exportable, ResultNotFound, export_source, put_json, source_folder
from .services import read_run_result_bytes


@export_source('run')
def resolve_run(user, run_id):
    run = DtRun.objects.filter(pk=run_id, user=user, status=DtRun.Status.COMPLETED).exclude(result_key='').first()
    if run is None:
        raise ResultNotFound
    return Exportable(
        twin_slug=run.twin_slug,
        source_key=run.result_key,
        name=f'{run.twin_slug}-{run.operation}-run-{run.pk}',
        filename='result.json',
        # Stored gzipped; JupyterHub gets plain JSON.
        write=put_json(lambda: read_run_result_bytes(run)),
    )


def run_source_prefix(run):
    """'' for a run without a stored result: nothing of it can have been exported."""
    return source_folder(run.result_key) if run.result_key else ''
