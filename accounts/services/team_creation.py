from django.shortcuts import redirect
from django.core.exceptions import ValidationError

from ..forms import TeamCreateForm
from ..models import Team


def handle_create_team_post(request, profile, current_team, redirect_to):
    create_team_form = TeamCreateForm()
    open_create_modal = request.GET.get("create") == "1"

    if request.method == "POST" and request.POST.get("action") == "create_team":
        open_create_modal = True

        if current_team is None:
            create_team_form = TeamCreateForm(request.POST)

            if create_team_form.is_valid():

                team_name = create_team_form.cleaned_data["name"]
                team_description = create_team_form.cleaned_data["description"]
                
                try:
                    new_team = Team.objects.create_team_assign_admin(
                        creator=request.user,
                        name=team_name,
                        description=team_description,
                    )
                    return create_team_form, False, new_team, redirect(redirect_to)
                
                except ValidationError as e:
                    create_team_form.add_error(None, str(e))
        else:
            return create_team_form, False, current_team, redirect(redirect_to)

    return create_team_form, open_create_modal, current_team, None