"""Keep the MLflow server in step with deleted experiments and accounts.

Covers the deletes that don't go through the project/experiment delete views -
the CASCADE from deleting the creator's account (of the project or of the
experiment), where the runs and artifacts are their personal data, the admin, a
queryset delete. The views clean up MLflow themselves, before the row, so they
can tell the user when that fails; they flag the instance so it isn't cleaned up
twice. Nothing is touched before the delete commits, so a rolled-back delete
keeps its MLflow experiment.
"""

from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django_q.tasks import async_task

from .models import Experiment

# Set by _delete_experiment_strict on the instance it deletes
MLFLOW_ALREADY_REMOVED = '_mlflow_already_removed'


@receiver(post_delete, sender=Experiment, dispatch_uid='experiment_delete_mlflow')
def delete_mlflow_experiment(sender, instance, **kwargs):
    """A deleted experiment takes its MLflow experiment and stored artifacts with it."""
    if getattr(instance, MLFLOW_ALREADY_REMOVED, False):
        return
    if not instance.mlflow_experiment_id:
        return

    # On the qcluster, not in the request: each MLflow call can take up to its
    # 15 s timeout, and an account can hold many experiments.
    transaction.on_commit(partial(
        async_task,
        'projects.tasks.discard_mlflow_experiment',
        mlflow_experiment_id=instance.mlflow_experiment_id,
    ))


@receiver(post_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid='user_delete_mlflow_user')
def delete_mlflow_user(sender, instance, **kwargs):
    """A deleted account takes its MLflow-OIDC user (created by accounts.models.create_user_profile) with it."""
    if not instance.email:
        return
    transaction.on_commit(partial(
        async_task,
        'projects.tasks.discard_mlflow_user',
        username=instance.email,
    ))
