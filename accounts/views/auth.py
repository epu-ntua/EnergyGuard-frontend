from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login, logout as django_logout
from django.shortcuts import redirect, render
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter
from allauth.socialaccount.providers.oauth2.views import OAuth2LoginView

from ..forms import CustomAuthenticationForm


class _KeycloakRegistrationAdapter(OpenIDConnectOAuth2Adapter):
    @property
    def authorize_url(self):
        auth_url = self.openid_config["authorization_endpoint"]
        return auth_url.rsplit("/auth", 1)[0] + "/registrations"


class _KeycloakRegistrationLoginView(OAuth2LoginView):
    def get_provider(self):
        provider = super().get_provider()
        provider.oauth2_adapter_class = _KeycloakRegistrationAdapter
        original = provider.get_auth_params_from_request

        def get_auth_params_without_prompt(request, action):
            params = original(request, action)
            params.pop("prompt", None)
            return params

        provider.get_auth_params_from_request = get_auth_params_without_prompt
        return provider


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user:
                login(request, user)
                return redirect("dashboard")
    else:
        form = CustomAuthenticationForm()

    return render(request, "accounts/login.html", {"form": form})


@require_POST
def keycloak_logout(request):
    post_logout_redirect_uri = request.build_absolute_uri(
        getattr(settings, "LOGOUT_REDIRECT_URL", "/") or "/"
    )
    end_session_url = None

    provider_config = settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {}).get(
        "APPS", [{}]
    )[0]
    server_url = provider_config.get("settings", {}).get("server_url")
    client_id = provider_config.get("client_id")

    if server_url:
        end_session_url = f"{server_url}/protocol/openid-connect/logout"

    if not end_session_url:
        return redirect(post_logout_redirect_uri)

    django_logout(request)

    params = {"post_logout_redirect_uri": post_logout_redirect_uri}
    if client_id:
        params["client_id"] = client_id

    return redirect(f"{end_session_url}?{urlencode(params)}")

def keycloak_register(request):
    view = _KeycloakRegistrationLoginView.adapter_view(_KeycloakRegistrationAdapter(request, "keycloak"))
    return view(request)


def keycloak_front_channel_logout(request):
    """
    Front-channel logout endpoint for Keycloak.
    Keycloak loads this URL in the user's browser (iframe) when any client
    triggers a logout, so the session cookie is present and we can clear it.
    Always returns 200 so Keycloak considers the logout successful.
    """
    django_logout(request)
    return HttpResponse(status=200)


def pending_approval(request):
    if request.user.is_authenticated:
        return redirect('home')
    if not request.session.get('pending_approval'):
        return redirect('home')
    return render(request, 'accounts/pending_approval.html', {
        'pending_user_name': request.session.get('pending_user_name', ''),
    })