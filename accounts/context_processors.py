from django.urls import reverse

from .models import Profile


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

    team_missing = profile is None or not profile.team or profile.team == Profile.TeamChoices.OTHER
    if team_missing:
        notifications.append(
            {
                "message": "Add Team to collaborate with people",
                "url": reverse("profile"),
                "icon": "users",
            }
        )

    return {
        "header_notifications": notifications,
        "header_notifications_count": len(notifications),
    }
