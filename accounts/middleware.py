import logging
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth import logout
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone

from allauth.socialaccount.models import SocialAccount, SocialToken

logger = logging.getLogger(__name__)

# Refresh the token a bit before it actually expires to avoid race conditions
_REFRESH_MARGIN = timedelta(seconds=30)

# Only one request may refresh a given token at a time. The platform polls
# (notifications, job status, RDN status), so several requests routinely arrive
# inside the refresh window at once. With Keycloak refresh-token rotation the
# first refresh invalidates the token the others are holding, so without this
# lock the losers get a non-200 and the user is logged out mid-task.
_REFRESH_LOCK_TIMEOUT = 15   # seconds a refresh is allowed to hold the lock
_REFRESH_WAIT_TIMEOUT = 10   # seconds a loser waits for the winner's result
_REFRESH_WAIT_INTERVAL = 0.2


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


def _token_is_fresh(social_token):
    return bool(
        social_token.expires_at
        and social_token.expires_at - _REFRESH_MARGIN > timezone.now()
    )


def _await_concurrent_refresh(social_token):
    """Another request holds the refresh lock. Wait for it, then re-read the row.

    Returns True if that refresh produced a usable token, False if it never did.
    """
    deadline = time.monotonic() + _REFRESH_WAIT_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(_REFRESH_WAIT_INTERVAL)
        social_token.refresh_from_db()
        if _token_is_fresh(social_token):
            return True
        if not cache.get(_refresh_lock_key(social_token)):
            # The winner finished without producing a fresh token.
            return False
    logger.warning("Timed out waiting for a concurrent Keycloak refresh of token %s", social_token.pk)
    return False


def _refresh_lock_key(social_token):
    return f"keycloak_token_refresh_{social_token.pk}"


def refresh_access_token(social_token):
    """Refresh `social_token`, ensuring only one request per token does so.

    Returns True if the token is usable afterwards, False if the session is over.
    """
    lock_key = _refresh_lock_key(social_token)
    # cache.add is atomic on the DatabaseCache backend, so exactly one caller wins.
    if not cache.add(lock_key, 1, timeout=_REFRESH_LOCK_TIMEOUT):
        return _await_concurrent_refresh(social_token)

    try:
        # Re-read inside the lock: another process may have refreshed between our
        # expiry check and acquiring it, in which case there is nothing to do.
        social_token.refresh_from_db()
        if _token_is_fresh(social_token):
            return True
        return _refresh_access_token(social_token)
    finally:
        cache.delete(lock_key)


def _refresh_access_token(social_token):
    """Use the refresh token to obtain a new access token from Keycloak.

    Returns True on success, False on failure (refresh token expired / revoked).
    Callers must hold the refresh lock - use `refresh_access_token` instead.
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
            if not request.user.is_active:
                logout(request)
                return redirect("account_login")

            backend = request.session.get('_auth_user_backend', '')
            if 'ModelBackend' in backend:
                return self.get_response(request)

            _, social_token = _get_keycloak_token(request.user)

            if (
                social_token
                and social_token.expires_at
                and social_token.expires_at - _REFRESH_MARGIN <= timezone.now()
            ):
                if not refresh_access_token(social_token):
                    # Refresh token is also expired – session is truly over
                    logout(request)
                    return redirect("account_login")

        return self.get_response(request)
