from django.db import transaction
from django.shortcuts import redirect

from ..forms import TeamCreateForm


def handle_create_team_post(request, profile, current_team, redirect_to):
    create_team_form = TeamCreateForm()
    open_create_modal = request.GET.get("create") == "1"

    if request.method == "POST" and request.POST.get("action") == "create_team":
        open_create_modal = True

        if current_team is None:
            create_team_form = TeamCreateForm(request.POST)
            create_team_form.instance.creator = request.user
            if create_team_form.is_valid():
                with transaction.atomic():
                    new_team = create_team_form.save()
                    profile.team = new_team
                    profile.save(update_fields=["team"])
                return create_team_form, False, new_team, redirect(redirect_to)
        else:
            return create_team_form, False, current_team, redirect(redirect_to)

    return create_team_form, open_create_modal, current_team, None