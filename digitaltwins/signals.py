"""Keep object storage and JupyterHub in step with deleted runs and exports.

Each receiver covers every path that deletes rows - the views, the admin, a
queryset delete, and the CASCADE from deleting the user's account, where the
files are their personal data. Nothing is touched before the delete commits, so
a rolled-back delete keeps its files. (BER requests: digitaltwins/ber/signals.py.)
"""

from functools import partial

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django_q.tasks import async_task

from .models import DtExport, DtRun, RdnSimulationJob
from .rdn.services.results import discard_result as discard_rdn_result
from .runs.services import discard_run_result
from .rdn.exports import rdn_source_prefix
from .runs.exports import run_source_prefix
from .services.jupyterhub_export import remove_exports


@receiver(post_delete, sender=DtRun, dispatch_uid='dt_run_delete_result')
def delete_run_files(sender, instance, **kwargs):
    """A deleted run takes its stored result and its JupyterHub copies with it."""
    remove_exports(user_id=instance.user_id, source_prefix=run_source_prefix(instance))
    if instance.result_key:
        transaction.on_commit(partial(discard_run_result, instance.result_key))


@receiver(post_delete, sender=RdnSimulationJob, dispatch_uid='rdn_job_delete_result')
def delete_rdn_job_files(sender, instance, **kwargs):
    """A deleted RDN job takes its stored result and its JupyterHub copies with it."""
    if instance.rdn_request_id is not None:
        remove_exports(user_id=instance.user_id, source_prefix=rdn_source_prefix(instance.rdn_request_id))
    if instance.result_key:
        transaction.on_commit(partial(discard_rdn_result, instance.result_key))


@receiver(post_delete, sender=DtExport, dispatch_uid='dt_result_delete_copy')
def delete_export_copy(sender, instance, **kwargs):
    """A deleted export takes its datasets-bucket copy and its JupyterHub file with it."""
    # Read now, inside the delete: when the whole account is being deleted, the
    # user row is gone by the time the task runs.
    email = get_user_model().objects.filter(pk=instance.user_id).values_list('email', flat=True).first()
    # On the qcluster, not in the request: the JupyterHub call can take up to its
    # 15 s timeout per copy. The ORM broker queues the task in this same
    # transaction, so a rolled-back delete never enqueues it.
    async_task(
        'digitaltwins.services.jupyterhub_export.discard_export',
        bucket_name=instance.bucket_name, result_key=instance.result_key, email=email,
    )
