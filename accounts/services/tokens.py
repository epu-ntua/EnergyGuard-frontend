import logging

import jwt
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.utils import timezone

logger = logging.getLogger(__name__)


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


def user_has_realm_role(user, role):
    """Return True if the user's Keycloak access token grants the given realm role.

    Reads the role straight out of the (already-validated-by-Keycloak) access token
    instead of calling the Keycloak admin API, so this is cheap enough for per-request
    checks. The signature isn't re-verified here since we're only reading a claim from
    a token allauth already obtained through the trusted OIDC flow.
    """
    access_token = get_user_access_token(user)
    if not access_token:
        return False

    try:
        claims = jwt.decode(access_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        logger.exception("Failed to decode Keycloak access token for user %s", user.email)
        return False

    realm_access = claims.get("realm_access") or {}
    return role in realm_access.get("roles", [])
