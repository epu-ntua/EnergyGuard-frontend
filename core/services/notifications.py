"""Helpers shared by the background tasks that notify users (BER, dataset review)."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def platform_link(path):
    """Absolute link for emails; tasks run outside a request, so it comes from settings."""
    return f'{settings.PLATFORM_URL.rstrip("/")}{path}'


def users_with_permission(app_label, codename):
    """Active users granted the permission, directly or through a group. Superusers
    hold every permission implicitly but are left out: the staff for a job is whoever
    the permission was actually given to."""
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission
    from django.db.models import Q

    permission = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
    if permission is None:
        return get_user_model().objects.none()
    return get_user_model().objects.filter(
        Q(user_permissions=permission) | Q(groups__permissions=permission),
        is_active=True,
    ).distinct()


def notify_in_app(recipient, *, message, url, icon):
    """The bell notification. Its failure is logged, not raised, so an email that
    follows still goes out: the recipient should get at least one of the two."""
    from accounts.models import Notification

    try:
        Notification.objects.create(recipient=recipient, message=message[:255], url=url, icon=icon)
    except Exception:
        logger.exception('Failed to create notification for user %s', recipient.pk)
