from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from ..forms import TeamCreateForm
from ..models import Profile

@login_required
def team_management(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    team = profile.team or getattr(request.user, "created_team", None)
    is_team_admin = bool(team and team.creator_id == request.user.id)

    create_team_form = TeamCreateForm()
    open_create_modal = request.GET.get("create") == "1"

    if request.method == "POST" and request.POST.get("action") == "create_team":
        open_create_modal = True
        if team is None:
            create_team_form = TeamCreateForm(request.POST)
            create_team_form.instance.creator = request.user
            if create_team_form.is_valid():
                with transaction.atomic():
                    new_team = create_team_form.save()
                    profile.team = new_team
                    profile.save(update_fields=["team"])
                return redirect("team_management")
        else:
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
        },
    )
