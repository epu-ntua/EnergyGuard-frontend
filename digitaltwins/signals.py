"""Keep object storage and JupyterHub in step with deleted runs and exports.

Each receiver covers every path that deletes rows - the views, the admin, a
queryset delete, and the CASCADE from deleting the user's account, where the
files are their personal data. Storage is touched only after commit, so a
rolled-back delete keeps its files. (BER requests: digitaltwins/ber/signals.py.)
"""

from functools import partial

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DtResult, DtRun, RdnSimulationJob
from .rdn.services.results import discard_result as discard_rdn_result
from .runs.services import discard_run_result
from .services.jupyterhub_export import discard_export, rdn_source_prefix, remove_exports, run_source_prefix


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


@receiver(post_delete, sender=DtResult, dispatch_uid='dt_result_delete_copy')
def delete_export_copy(sender, instance, **kwargs):
    """A deleted export takes its datasets-bucket copy and its JupyterHub file with it."""
    # Read now, inside the delete: when the whole account is being deleted, the
    # user row is gone by the time on_commit callbacks run.
    email = get_user_model().objects.filter(pk=instance.user_id).values_list('email', flat=True).first()
    transaction.on_commit(partial(
        discard_export, bucket_name=instance.bucket_name, result_key=instance.result_key, email=email,
    ))
