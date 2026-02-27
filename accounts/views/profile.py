import logging
import os

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..forms import ProfileEditForm, ProfileUpdateForm
from ..models import Profile
from ..services.keycloak_user_sync import KeycloakUserSyncClient
from ..services.team_creation import handle_create_team_post
from ..utils.dates import get_time_since_joined

logger = logging.getLogger(__name__)


def _sync_name_to_keycloak(user):
    keycloak_client = KeycloakUserSyncClient()
    if not keycloak_client.token:
        logger.error(
            "Keycloak client not initialized for user %s. Sync failed.",
            user.id,
        )
        return

    result = keycloak_client.update_user(
        user,
        {
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
    )
    if result.get("error"):
        logger.error("Keycloak sync failed for user %s: %s", user.id, result.get("error"))


def _update_user_name_from_full_name(user, full_name):
    if not full_name:
        return

    name_parts = full_name.split()
    if len(name_parts) < 2:
        return

    user.first_name = name_parts[0]
    user.last_name = " ".join(name_parts[1:])
    user.save(update_fields=["first_name", "last_name"])
    _sync_name_to_keycloak(user)


@login_required
def profile(request):
    joined_display = get_time_since_joined(request.user.date_joined)
    last_login = get_time_since_joined(request.user.last_login)

    user_profile, _ = Profile.objects.get_or_create(user=request.user)
    effective_team = user_profile.team or getattr(request.user, "created_team", None)
    user_projects_count = request.user.creator_projects.count()

    is_create_team_post = request.method == "POST" and request.POST.get("action") == "create_team"

    create_team_form, open_create_modal, effective_team, response = handle_create_team_post(
        request=request,
        profile=user_profile,
        current_team=effective_team,
        redirect_to="profile",
    )
    if response:
        return response

    if request.method == "POST" and not is_create_team_post:
        form = ProfileEditForm(request.POST, instance=user_profile, user=request.user)
        if form.is_valid():
            _update_user_name_from_full_name(request.user, form.cleaned_data.get("full_name"))
            form.save()
            return redirect("profile")
    else:
        form = ProfileEditForm(instance=user_profile, user=request.user)

    return render(
        request,
        "accounts/profile.html",
        {
            "show_sidebar": False,
            "joined_display": joined_display,
            "last_login": last_login,
            "form": form,
            "profile": user_profile,
            "effective_team": effective_team,
            "total_projects": user_projects_count,
            "create_team_form": create_team_form,
            "open_create_modal": open_create_modal, 
        },
    )


@login_required
def update_profile_picture(request):
    if request.method == "POST":
        profile_instance, _ = Profile.objects.get_or_create(user=request.user)
        old_picture_path = (
            profile_instance.profile_picture.path if profile_instance.profile_picture else None
        )

        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile_instance)
        if form.is_valid():
            if old_picture_path and os.path.exists(old_picture_path):
                os.remove(old_picture_path)
            form.save()

    return redirect("profile")
