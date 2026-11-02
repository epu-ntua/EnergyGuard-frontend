"""Keep object storage and JupyterHub in step with deleted datasets.

Covers the deletes that don't go through the dataset_delete view - the CASCADE
from deleting the publisher's account, where the files are their personal data,
the admin, a queryset delete. The view removes the files itself, before the row,
so it can tell the user when that fails; it flags the instance so they aren't
removed twice. Nothing is touched before the delete commits, so a rolled-back
delete keeps its files.
"""

from functools import partial

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django_q.tasks import async_task

from .models import Dataset

# Set by the dataset_delete view on the instance it deletes
FILES_ALREADY_REMOVED = '_files_already_removed'


@receiver(post_delete, sender=Dataset, dispatch_uid='dataset_delete_files')
def delete_dataset_files(sender, instance, **kwargs):
    """A deleted user dataset takes its MinIO object and the publisher's JupyterHub copy with it."""
    if getattr(instance, FILES_ALREADY_REMOVED, False):
        return
    # Platform-owned data (the pilot datasets) points at shared files that
    # seed_pilot_datasets deletes and recreates rows for; never remove those.
    if instance.publisher_id is None:
        return

    # Read now, inside the delete: when the whole account is being deleted, the
    # user row is gone by the time the task runs. JupyterHub identifies users by email.
    email = get_user_model().objects.filter(pk=instance.publisher_id).values_list('email', flat=True).first()
    transaction.on_commit(partial(
        async_task,
        'datasets.tasks.discard_dataset_files',
        bucket_name=instance.bucket_name,
        data_file_key=instance.data_file,
        email=email,
        dataset_name=instance.name,
    ))
