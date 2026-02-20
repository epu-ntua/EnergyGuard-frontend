import logging
import os
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..forms import ProfileForm, ProfileUpdateForm
from ..models import Profile
from ..services.keycloak_user_sync import KeycloakUserSyncClient
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


def _parse_birth_date(year_of_birth, month_of_birth, day_of_birth):
    if not (
        year_of_birth
        and year_of_birth != ""
        and month_of_birth
        and month_of_birth != ""
        and day_of_birth
        and day_of_birth != ""
    ):
        return None

    try:
        return date(int(year_of_birth), int(month_of_birth), int(day_of_birth))
    except (ValueError, TypeError):
        return None


def _build_profile_initial_data(user, user_profile):
    initial_data = {
        "team": user_profile.team or "",
        "position": user_profile.position or "",
        "short_bio": user_profile.bio or "",
        "full_name": f"{user.first_name} {user.last_name}".strip(),
    }

    if user_profile.birth_date:
        initial_data["year_of_birth"] = str(user_profile.birth_date.year)
        initial_data["month_of_birth"] = str(user_profile.birth_date.month)
        initial_data["day_of_birth"] = str(user_profile.birth_date.day)

    return initial_data


@login_required
def profile(request):
    joined_display = get_time_since_joined(request.user.date_joined)
    last_login = get_time_since_joined(request.user.last_login)

    user_profile, _ = Profile.objects.get_or_create(user=request.user)
    user_projects_count = request.user.creator_projects.count()

    if request.method == "POST":
        form = ProfileForm(request.POST)
        if form.is_valid():
            _update_user_name_from_full_name(request.user, form.cleaned_data.get("full_name"))

            team = form.cleaned_data.get("team")
            if team:
                user_profile.team = team

            position = form.cleaned_data.get("position")
            if position:
                user_profile.position = position

            birth_date = _parse_birth_date(
                form.cleaned_data.get("year_of_birth"),
                form.cleaned_data.get("month_of_birth"),
                form.cleaned_data.get("day_of_birth"),
            )
            if birth_date is not None:
                user_profile.birth_date = birth_date

            short_bio = form.cleaned_data.get("short_bio")
            if short_bio:
                user_profile.bio = short_bio

            user_profile.save()
            return redirect("profile")
    else:
        form = ProfileForm(initial=_build_profile_initial_data(request.user, user_profile))

    return render(
        request,
        "accounts/profile.html",
        {
            "show_sidebar": False,
            "joined_display": joined_display,
            "last_login": last_login,
            "form": form,
            "profile": user_profile,
            "total_projects": user_projects_count,
        },
    )


@login_required
def update_profile_picture(request):
    if request.method == "POST":
        profile_instance = request.user.profile
        old_picture_path = (
            profile_instance.profile_picture.path if profile_instance.profile_picture else None
        )

        form = ProfileUpdateForm(request.POST, request.FILES, instance=profile_instance)
        if form.is_valid():
            if old_picture_path and os.path.exists(old_picture_path):
                os.remove(old_picture_path)
            form.save()

    return redirect("profile")
