from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django_datatables_view.base_datatable_view import BaseDatatableView

from ..models import Dataset


class DatasetsListJson(BaseDatatableView):
    model = Dataset
    columns = [
        "name",
        "created_at",
        "label",
        "source",
        "publisher",
        "size_gb",
        "status",
        "id",
    ]
    order_columns = [
        "name",
        "created_at",
        "label",
        "source",
        "publisher",
        "size_gb",
        "status",
    ]
    max_display_length = 25

    def get_initial_queryset(self):
        return Dataset.objects.annotate(projects_count=Count("projects", distinct=True))

    def filter_queryset(self, qs):
        scope = self.request.GET.get("scope", "public")
        if scope == "my":
            qs = qs.filter(publisher=self.request.user)
        else:
            qs = qs.filter(visibility=True).exclude(publisher=self.request.user)

        search = self.request.GET.get("search[value]")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(label__icontains=search)
                | Q(source__icontains=search)
                | Q(status__icontains=search)
            ).distinct()

        allowed_labels = [value for value, _ in Dataset.Label.choices]
        label_filter = self.request.GET.get("label")
        if label_filter in allowed_labels:
            qs = qs.filter(label=label_filter)

        return qs

    def render_column(self, row, column):
        if column == "created_at":
            return row.created_at.strftime("%b %d, %Y")
        if column == "publisher":
            return row.publisher_display
        if column == "label":
            return row.get_label_display()
        if column == "source":
            return row.get_source_display()
        if column == "size_gb":
            return row.size_gb
        if column == "status":
            scope = self.request.GET.get("scope", "public")
            if scope == "public":
                return row.projects_count

            status = row.status.replace("_", " ").title()
            status_badge_map = {
                "approved": "badge-phoenix-success",
                "under_review": "badge-phoenix-primary",
                "rejected": "badge-phoenix-danger",
            }
            badge_class = status_badge_map.get(row.status, "badge-phoenix-secondary")
            return (
                '<div class="text-end"><span class="badge badge-phoenix '
                f'{badge_class} fs-11"><span class="badge-label">{status}'
                "</span></span></div>"
            )
        return super().render_column(row, column)


@login_required
def datasets_list(request):
    my_qs = Dataset.objects.filter(publisher=request.user)
    public_qs = Dataset.objects.filter(visibility=True).exclude(publisher=request.user)

    active_tab = request.GET.get("tab", "public")
    if active_tab not in ["public", "my"]:
        active_tab = "public"

    label_filter = request.GET.get("label")
    allowed_labels = [value for value, _ in Dataset.Label.choices]
    if label_filter not in allowed_labels:
        label_filter = None

    label_tabs = [
        {
            "value": value,
            "display": display,
            "public_count": public_qs.filter(label=value).count(),
            "my_count": my_qs.filter(label=value).count(),
        }
        for value, display in Dataset.Label.choices
    ]

    return render(
        request,
        "datasets/datasets-list.html",
        {
            "public_datasets_num": {"all": public_qs.count()},
            "my_datasets_num": {"all": my_qs.count()},
            "active_tab": active_tab,
            "label_filter": label_filter,
            "label_tabs": label_tabs,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )
