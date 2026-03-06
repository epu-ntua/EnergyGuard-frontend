from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import TeamEditForm, TeamInviteForm
from ..models import Profile, TeamInvite, User
from ..services.team_creation import handle_create_team_post
from ..services.team_invite import accept_team_invite, decline_team_invite, send_team_invite

@login_required
def team_management(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    team = profile.team
    is_team_admin = bool(profile.team_role == Profile.Team_Role.ADMIN and team)

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

    invite_form = TeamInviteForm()
    invite_error = None
    open_invite_modal = False

    if request.method == "POST" and request.POST.get("action") == "send_invite":
        open_invite_modal = True
        if not team or not is_team_admin:
            return redirect("team_management")
        invite_form = TeamInviteForm(request.POST)
        if invite_form.is_valid():
            _, error = send_team_invite(
                request=request,
                team=team,
                email=invite_form.cleaned_data["email"],
                invited_by=request.user,
            )
            if error:
                invite_error = error
            else:
                messages.success(request, "Invitation sent successfully.")
                return redirect("team_management")

    if team:
        team_members = team.members.select_related("user__profile").order_by("user__last_name", "user__first_name")
        team_members_count = team.members.count()
        if is_team_admin:
            pending_invites = list(
                TeamInvite.objects.filter(team=team, accepted_at__isnull=True)
                .order_by("-created_at")
            )
            user_map = {
                u.email: u
                for u in User.objects.filter(email__in=[i.email for i in pending_invites])
            }
            for invite in pending_invites:
                invite.platform_user = user_map.get(invite.email)
        else:
            pending_invites = []
    else:
        team_members = []
        team_members_count = 0
        pending_invites = []

    received_invites = TeamInvite.objects.filter(
        email=request.user.email,
        accepted_at__isnull=True,
        declined_at__isnull=True,
    ).select_related('team', 'invited_by').prefetch_related('team__members__user')

    return render(
        request,
        "accounts/team_management.html",
        {
            "team": team,
            "is_team_admin": is_team_admin,
            "team_members": team_members,
            "team_members_count": team_members_count,
            "pending_invites": pending_invites,
            "create_team_form": create_team_form,
            "open_create_modal": open_create_modal,
            "edit_team_form": edit_team_form,
            "open_edit_modal": open_edit_modal,
            "invite_form": invite_form,
            "invite_error": invite_error,
            "open_invite_modal": open_invite_modal,
            "received_invites": received_invites,
        },
    )


@login_required
def accept_invite(request, token):
    team, error = accept_team_invite(token=token, user=request.user)
    if error:
        return render(request, "accounts/accept_invite_error.html", {"error": error})
    messages.success(request, f"You have successfully joined {team.name}!")
    return redirect("team_management")


@login_required
def decline_invite(request, token):
    if request.method != "POST":
        return redirect("team_management")
    error = decline_team_invite(token=token, user=request.user)
    if error:
        messages.error(request, error)
    else:
        messages.info(request, "Invitation declined.")
    return redirect("team_management")
