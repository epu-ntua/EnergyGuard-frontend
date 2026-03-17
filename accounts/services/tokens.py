from allauth.socialaccount.models import SocialAccount, SocialToken
from django.utils import timezone


def get_user_access_token(user):
    """Return the Keycloak access token for an authenticated user, or None if expired."""
    if not user or not getattr(user, "is_authenticated", False):
        return None

    social_account = (
        SocialAccount.objects
        .filter(user=user, provider="keycloak")
        .order_by("-pk")
        .first()
    )
    if not social_account:
        return None

    social_token = (
        SocialToken.objects
        .filter(account=social_account)
        .order_by("-expires_at", "-pk")
        .first()
    )
    if social_token and social_token.token:
        if social_token.expires_at and social_token.expires_at <= timezone.now():
            return None
        return social_token.token

    return None
