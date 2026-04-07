import logging

import requests
from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

from allauth.socialaccount.models import SocialAccount, SocialToken

logger = logging.getLogger(__name__)


class KeycloakTokenExpiryMiddleware:
    """
    Refresh the Keycloak access token when it has expired, using the stored
    refresh token. Only logs the user out if the refresh itself fails.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            social_account = (
                SocialAccount.objects
                .filter(user=request.user, provider="keycloak")
                .order_by("-pk")
                .first()
            )
            if social_account:
                social_token = (
                    SocialToken.objects
                    .filter(account=social_account)
                    .order_by("-expires_at", "-pk")
                    .first()
                )
                if (
                    social_token
                    and social_token.expires_at
                    and social_token.expires_at <= timezone.now()
                ):
                    if not self._refresh_token(social_token):
                        logout(request)
                        return redirect("account_login")

        return self.get_response(request)

    def _refresh_token(self, social_token):
        """
        Exchange the refresh token for a new access token.
        Updates the SocialToken record in-place and returns True on success.
        """
        refresh_token = social_token.token_secret
        if not refresh_token:
            logger.warning("KeycloakTokenExpiryMiddleware: no refresh token stored, forcing logout.")
            return False

        provider_config = (
            settings.SOCIALACCOUNT_PROVIDERS
            .get("openid_connect", {})
            .get("APPS", [{}])[0]
        )
        server_url = provider_config.get("settings", {}).get("server_url", "").rstrip("/")
        client_id = provider_config.get("client_id")
        client_secret = provider_config.get("secret")

        token_endpoint = f"{server_url}/protocol/openid-connect/token"

        try:
            response = requests.post(
                token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.error("KeycloakTokenExpiryMiddleware: token refresh request failed: %s", exc)
            return False

        if response.status_code != 200:
            logger.warning(
                "KeycloakTokenExpiryMiddleware: refresh returned HTTP %s — forcing logout.",
                response.status_code,
            )
            return False

        data = response.json()
        social_token.token = data["access_token"]
        social_token.token_secret = data.get("refresh_token", refresh_token)
        expires_in = data.get("expires_in", 300)
        social_token.expires_at = timezone.now() + timezone.timedelta(seconds=expires_in)
        social_token.save(update_fields=["token", "token_secret", "expires_at"])
        logger.debug("KeycloakTokenExpiryMiddleware: token refreshed successfully.")
        return True
