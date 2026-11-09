from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete
from django.dispatch import receiver


@receiver(post_delete, sender=settings.AUTH_USER_MODEL, dispatch_uid='user_delete_admin_log')
def anonymise_admin_log(sender, instance, **kwargs):
    """The admin log names each changed object by its str(), the email for a user,
    and has no foreign key to it, so the entries outlive the account. They stay,
    as the record of what the admins did, under the account's id instead. Includes
    the "Deleted" entry, which the admin writes before the delete."""
    LogEntry.objects.filter(
        content_type=ContentType.objects.get_for_model(sender),
        object_id=str(instance.pk),
    ).update(object_repr=f'Deleted user #{instance.pk}')
