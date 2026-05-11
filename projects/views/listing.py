from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django_datatables_view.base_datatable_view import BaseDatatableView

from ..models import Project


class ProjectsListJson(BaseDatatableView):
    model = Project
    columns = [
        "name",
        "description",
        "collaborators",
        "created_at",
        "updated_at",
        "project_type",
        "id",
    ]
    order_columns = [
        "name",
        "description",
        "collaborators__first_name",
        "created_at",
        "updated_at",
        "project_type",
    ]
    max_display_length = 25

    def get_initial_queryset(self):
        return Project.objects.prefetch_related("collaborators").all()

    def render_column(self, row, column):
        if column == "created_at":
            return row.created_at.strftime("%b %d, %Y")
        if column == "updated_at":
            return row.updated_at.strftime("%b %d, %Y")
        if column == "collaborators":
            return ", ".join(user.first_name for user in row.collaborators.all()) or "No collaborators"
        if column == "project_type":
            return row.get_project_type_display()
        return super().render_column(row, column)

    def filter_queryset(self, qs):
        user = self.request.user
        scope = self.request.GET.get("scope", "my")

        if scope == "public":
            qs = qs.filter(visibility=True)
            if user.is_authenticated:
                qs = qs.exclude(creator_id=user.id)
        elif user.is_authenticated:
            try:
                team = user.profile.team
            except Exception:
                team = None
            if team is not None:
                qs = qs.filter(team=team)
            else:
                qs = qs.filter(creator_id=user.id, team__isnull=True)
        else:
            qs = qs.none()

        search = self.request.GET.get("search[value]")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search)).distinct()

        allowed_types = [value for value, _ in Project.ProjectType.choices]
        type_filter = self.request.GET.get("type")
        if type_filter in allowed_types:
            qs = qs.filter(project_type=type_filter)
        return qs


@login_required
def projects_list(request):
    try:
        team = request.user.profile.team
    except Exception:
        team = None

    if team is not None:
        my_qs = Project.objects.filter(team=team)
    else:
        my_qs = Project.objects.filter(creator_id=request.user.id, team__isnull=True)

    public_qs = Project.objects.filter(visibility=True).exclude(creator_id=request.user.id)

    my_counts = {
        "all": my_qs.count(),
    }
    public_counts = {
        "all": public_qs.count(),
    }

    type_tabs = [
        {
            "value": value,
            "display": display,
            "my_count": my_qs.filter(project_type=value).count(),
            "public_count": public_qs.filter(project_type=value).count(),
        }
        for value, display in Project.ProjectType.choices
    ]

    type_filter = request.GET.get("type")
    allowed_types = [value for value, _ in Project.ProjectType.choices]
    if type_filter not in allowed_types:
        type_filter = None

    active_tab = request.GET.get("tab", "my")
    if active_tab not in ["my", "public"]:
        active_tab = "my"

    return render(
        request,
        "projects/projects-list.html",
        {
            "my_projects_num": my_counts,
            "public_projects_num": public_counts,
            "type_tabs": type_tabs,
            "type_filter": type_filter,
            "active_tab": active_tab,
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )
