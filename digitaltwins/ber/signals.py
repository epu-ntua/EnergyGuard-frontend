"""Keep object storage in step with deleted BER requests."""

from functools import partial

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from digitaltwins.models import BerExperimentRequest

from ..services.jupyterhub_export import remove_exports
from .exports import ber_source_prefix
from .services.storage import discard_result_file


@receiver(post_delete, sender=BerExperimentRequest, dispatch_uid='ber_delete_result_file')
def delete_result_file_with_request(sender, instance, **kwargs):
    """A deleted request takes its result file with it.

    Covers every path that deletes rows - the admin, a queryset delete, and the
    CASCADE from deleting the requester's account, where the file is their
    personal data. Runs after commit, so a rolled-back delete keeps its file.
    The requester's JupyterHub copies of the result go too.
    """
    remove_exports(user_id=instance.user_id, source_prefix=ber_source_prefix(instance.pk))
    if instance.result_key:
        transaction.on_commit(partial(discard_result_file, instance.result_key, instance.pk, 'request deleted'))
