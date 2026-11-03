from django.urls import reverse
from django.utils import timezone
from .models import Notification, Profile


def header_notifications(request):
    if not request.user.is_authenticated:
        return {
            "header_notifications": [],
            "header_notifications_count": 0,
            "header_notifications_limit": Notification.DROPDOWN_LIMIT,
            "current_user_profile": None,
        }

    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = None

    # Taken before the query: the poll only toasts notifications created after it, so an
    # old unread one that slides into the dropdown window is not announced as new.
    rendered_at = timezone.now()
    unread = Notification.objects.filter(recipient=request.user, is_read=False)
    notifications = [
        {
            "id": n.id,
            "message": n.message,
            "url": reverse("read_notification", args=[n.id]),
            "icon": n.icon,
            "created_at": n.created_at,
        }
        for n in unread[:Notification.DROPDOWN_LIMIT]
    ]

    return {
        "header_notifications": notifications,
        "header_notifications_count": unread.count(),
        "header_notifications_limit": Notification.DROPDOWN_LIMIT,
        "header_notifications_rendered_at_ms": int(rendered_at.timestamp() * 1000),
        "current_user_profile": profile,
    }
