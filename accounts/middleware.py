from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

from allauth.socialaccount.models import SocialAccount, SocialToken


class KeycloakTokenExpiryMiddleware:
    """
    Log out users whose Keycloak access token has expired, mirroring
    when MLflow's OIDC plugin would reject the same token.
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
                    logout(request)
                    return redirect("account_login")

        return self.get_response(request)
