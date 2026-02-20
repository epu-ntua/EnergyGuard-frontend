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
        scope = self.request.GET.get("scope", "my")
        if scope == "public":
            qs = qs.filter(visibility=True)
            if self.request.user.is_authenticated:
                qs = qs.exclude(creator_id=self.request.user.id)
        elif self.request.user.is_authenticated:
            qs = qs.filter(creator_id=self.request.user.id)
        else:
            qs = qs.none()

        search = self.request.GET.get("search[value]")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(description__icontains=search)).distinct()

        type_filter = self.request.GET.get("type")
        if type_filter in [
            "ai_model",
            "ai_service",
            "web_app",
            "mobile_app",
            "iot_integration",
            "data_pipeline",
        ]:
            qs = qs.filter(project_type=type_filter)
        return qs


@login_required
def projects_list(request):
    my_qs = Project.objects.filter(creator_id=request.user.id)
    public_qs = Project.objects.filter(visibility=True).exclude(creator_id=request.user.id)

    my_counts = {
        "all": my_qs.count(),
        "ai_model": my_qs.filter(project_type="ai_model").count(),
        "ai_service": my_qs.filter(project_type="ai_service").count(),
        "web_app": my_qs.filter(project_type="web_app").count(),
        "mobile_app": my_qs.filter(project_type="mobile_app").count(),
        "iot_integration": my_qs.filter(project_type="iot_integration").count(),
        "data_pipeline": my_qs.filter(project_type="data_pipeline").count(),
    }
    public_counts = {
        "all": public_qs.count(),
        "ai_model": public_qs.filter(project_type="ai_model").count(),
        "ai_service": public_qs.filter(project_type="ai_service").count(),
        "web_app": public_qs.filter(project_type="web_app").count(),
        "mobile_app": public_qs.filter(project_type="mobile_app").count(),
        "iot_integration": public_qs.filter(project_type="iot_integration").count(),
        "data_pipeline": public_qs.filter(project_type="data_pipeline").count(),
    }

    type_filter = request.GET.get("type")
    active_tab = request.GET.get("tab", "my")
    if active_tab not in ["my", "public"]:
        active_tab = "my"

    return render(
        request,
        "projects/projects-list.html",
        {
            "my_projects_num": my_counts,
            "public_projects_num": public_counts,
            "type_filter": type_filter,
            "active_tab": active_tab,
            "active_navbar_page": "projects",
            "show_sidebar": True,
        },
    )


@login_required
def projects_list_tabs(request):
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("draw"):
        draw = int(request.GET.get("draw", 1))
        start = int(request.GET.get("start", 0))
        length = int(request.GET.get("length", 10))
        search_value = request.GET.get("search[value]", "")
        status_filter = request.GET.get("status")
        visibility_filter = request.GET.get("visibility", "false")

        order_col = request.GET.get("order[0][column]", "2")
        order_dir = request.GET.get("order[0][dir]", "desc")
        column_map = {
            "1": "name",
            "2": "collaborators__first_name",
            "3": "created_at",
            "4": "updated_at",
            "5": "status",
            "6": "type",
            "7": "progress",
            "8": "status",
        }
        ordering = column_map.get(order_col, "created_at")
        if order_dir == "desc":
            ordering = f"-{ordering}"

        qs = (
            Project.objects.select_related("creator")
            .prefetch_related("collaborators")
            .filter(visibility=visibility_filter == "true")
        )
        if status_filter in ["completed", "ongoing", "cancelled", "inactive"]:
            qs = qs.filter(status=status_filter)

        records_total = qs.count()

        if search_value:
            qs = qs.filter(Q(name__icontains=search_value)).distinct()

        records_filtered = qs.count()
        qs = qs.order_by(ordering)[start : start + length]

        data = []
        for exp in qs:
            data.append(
                {
                    "id": exp.id,
                    "name": exp.name,
                    "description": exp.description,
                    "collaborators": ", ".join(exp.collaborators.values_list("first_name", flat=True)),
                    "created_at": exp.created_at.strftime("%b %d, %Y"),
                    "updated_at": exp.updated_at.strftime("%b %d, %Y"),
                    "type": exp.get_project_type_display(),
                    "progress": exp.progress,
                    "status": exp.status,
                }
            )

        return JsonResponse(
            {
                "draw": draw,
                "recordsTotal": records_total,
                "recordsFiltered": records_filtered,
                "data": data,
            }
        )

    visibility_filter = request.GET.get("visibility", "false")
    data = Project.objects.filter(visibility=visibility_filter == "true")
    counts = {
        "all": data.count(),
        "completed": data.filter(status="completed").count(),
        "ongoing": data.filter(status="ongoing").count(),
        "cancelled": data.filter(status="cancelled").count(),
        "inactive": data.filter(status="inactive").count(),
    }
    status_filter = request.GET.get("status")
    return render(
        request,
        "projects/projects-list-tabs-test.html",
        {
            "project": data,
            "projects_num": counts,
            "status_filter": status_filter,
            "active_navbar_page": "projects",
            "show_sidebar": True,
            "visibility_filter": visibility_filter,
        },
    )
