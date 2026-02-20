from allauth.socialaccount.models import SocialAccount, SocialToken

def get_user_access_token(user):
    """Return the Keycloak access token for an authenticated user."""
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
        return social_token.token

    return None
