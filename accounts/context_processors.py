from django.urls import reverse

from .models import Notification, Profile


def header_notifications(request):
    if not request.user.is_authenticated:
        return {
            "header_notifications": [],
            "header_notifications_count": 0,
        }

    notifications = []

    try:
        profile = request.user.profile
    except Profile.DoesNotExist:
        profile = None

    unread = Notification.objects.filter(recipient=request.user, is_read=False)
    for n in unread:
        notifications.append(
            {
                "message": n.message,
                "url": reverse("read_notification", args=[n.id]),
                "icon": n.icon,
            }
        )

    team_missing = profile is None or profile.team_id is None
    if team_missing:
        notifications.append(
            {
                "message": "Add Team to collaborate with people",
                "url": reverse("team_management"),
                "icon": "users",
            }
        )

    profile_details_missing = (
        profile is None
        or not profile.position
        or not profile.birth_date
        or not profile.bio
    )
    if profile_details_missing:
        notifications.append(
            {
                "message": "Complete your profile for better experience",
                "url": reverse("profile"),
                "icon": "user",
            }
        )

    return {
        "header_notifications": notifications,
        "header_notifications_count": len(notifications),
    }
