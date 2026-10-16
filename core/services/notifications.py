"""Helpers shared by the background tasks that notify users (BER, dataset review)."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def platform_link(path):
    """Absolute link for emails; tasks run outside a request, so it comes from settings."""
    return f'{settings.PLATFORM_URL.rstrip("/")}{path}'


def notify_in_app(recipient, *, message, url, icon):
    """The bell notification. Its failure is logged, not raised, so an email that
    follows still goes out: the recipient should get at least one of the two."""
    from accounts.models import Notification

    try:
        Notification.objects.create(recipient=recipient, message=message[:255], url=url, icon=icon)
    except Exception:
        logger.exception('Failed to create notification for user %s', recipient.pk)
