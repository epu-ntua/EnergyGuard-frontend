from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import login, logout as django_logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from ..forms import CustomAuthenticationForm


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

# Signal handler to track new Keycloak signups
# @receiver(pre_social_login)
# def keycloak_signup_signal(sender, request, sociallogin, **kwargs):
#     """
#     Signal fired before social login completes.
#     Marks new signups in the session.
#     """
#     if sociallogin.account.provider == 'keycloak':
#         # Check if this is a new user (doesn't have a user object yet)
#         if not sociallogin.is_existing:
#             request.session['keycloak_new_signup'] = True

# def keycloak_redirect(request):
#     """
#     Custom redirect handler for Keycloak login/signup.
#     Redirects new signups to platform entry wizard
#     Redirects existing users to experiments
#     """
#     if not request.user.is_authenticated:
#         return redirect('login')
    
#     is_new_signup = request.session.pop('keycloak_new_signup', False)
    
#     # Also check if user has a profile - new users won't have one
#     has_profile = Profile.objects.filter(user=request.user).exists()
    
#     if is_new_signup or not has_profile:
#         # New user signup - redirect to platform entry wizard
#         return redirect('platform_entry')
#     else:
#         # Existing user login - redirect to experiments
#         return redirect('experiment_index')