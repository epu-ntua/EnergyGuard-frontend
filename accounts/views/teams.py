from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from ..forms import TeamEditForm
from ..models import Profile
from ..services.team_creation import handle_create_team_post

@login_required
def team_management(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    team = profile.team or getattr(request.user, "created_team", None)
    is_team_admin = bool(team and team.creator_id == request.user.id)

    create_team_form, open_create_modal, team, response = handle_create_team_post(
        request=request,
        profile=profile,
        current_team=team,
        redirect_to="team_management",
)

    if response:
        return response

    open_edit_modal = request.GET.get("edit") == "1"
    edit_team_form = TeamEditForm(instance=team) if (team and is_team_admin) else None

    if request.method == "POST" and request.POST.get("action") == "edit_team":
        open_edit_modal = True
        if not team or not is_team_admin:
            return redirect("team_management")
        edit_team_form = TeamEditForm(request.POST, instance=team)
        if edit_team_form.is_valid():
            edit_team_form.save()
            return redirect("team_management")

    team_members = []
    team_members_count = 0
    if team:
        team_members = list(
            team.members.select_related("user")
            .order_by("user__last_name", "user__first_name")
        )
        team_members_count = len(team_members)
        if all(member.user_id != team.creator_id for member in team_members):
            team_members_count += 1

    return render(
        request,
        "accounts/team_management.html",
        {
            "team": team,
            "is_team_admin": is_team_admin,
            "team_members": team_members,
            "team_members_count": team_members_count,
            "create_team_form": create_team_form,
            "open_create_modal": open_create_modal,
            "edit_team_form": edit_team_form,
            "open_edit_modal": open_edit_modal,
        },
    )
