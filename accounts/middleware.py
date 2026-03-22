import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

from allauth.socialaccount.models import SocialAccount, SocialToken

logger = logging.getLogger(__name__)

# Refresh the token a bit before it actually expires to avoid race conditions
_REFRESH_MARGIN = timedelta(seconds=30)


def _get_keycloak_token(user):
    """Return the SocialAccount and SocialToken for a Keycloak user, or (None, None)."""
    social_account = (
        SocialAccount.objects
        .filter(user=user, provider="keycloak")
        .order_by("-pk")
        .first()
    )
    if not social_account:
        return None, None

    social_token = (
        SocialToken.objects
        .filter(account=social_account)
        .order_by("-expires_at", "-pk")
        .first()
    )
    return social_account, social_token


def _refresh_access_token(social_token):
    """Use the refresh token to obtain a new access token from Keycloak.

    Returns True on success, False on failure (refresh token expired / revoked).
    """
    refresh_token = (social_token.token_secret or "").strip()
    if not refresh_token:
        return False

    provider_config = (
        settings.SOCIALACCOUNT_PROVIDERS
        .get("openid_connect", {})
        .get("APPS", [{}])[0]
    )
    server_url = provider_config.get("settings", {}).get("server_url", "")
    client_id = provider_config.get("client_id", "")
    client_secret = provider_config.get("secret", "")

    if not server_url or not client_id:
        return False

    token_url = f"{server_url}/protocol/openid-connect/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    try:
        response = requests.post(token_url, data=payload, timeout=10)
    except requests.RequestException:
        logger.warning("Keycloak token refresh request failed", exc_info=True)
        return False

    if response.status_code != 200:
        logger.info(
            "Keycloak token refresh returned %s – session expired",
            response.status_code,
        )
        return False

    data = response.json()
    new_access_token = data.get("access_token", "")
    new_refresh_token = data.get("refresh_token", "")
    expires_in = data.get("expires_in")

    if not new_access_token:
        return False

    social_token.token = new_access_token
    if new_refresh_token:
        social_token.token_secret = new_refresh_token
    if expires_in:
        social_token.expires_at = timezone.now() + timedelta(seconds=int(expires_in))

    social_token.save(update_fields=["token", "token_secret", "expires_at"])
    return True


class KeycloakTokenExpiryMiddleware:
    """
    Transparently refresh the Keycloak access token when it is about to
    expire.  Only log out the user when the refresh token itself has
    expired (i.e. the session is truly over).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            _, social_token = _get_keycloak_token(request.user)

            if (
                social_token
                and social_token.expires_at
                and social_token.expires_at - _REFRESH_MARGIN <= timezone.now()
            ):
                if not _refresh_access_token(social_token):
                    # Refresh token is also expired – session is truly over
                    logout(request)
                    return redirect("account_login")

        return self.get_response(request)
