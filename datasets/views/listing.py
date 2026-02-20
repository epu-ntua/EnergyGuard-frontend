from django.contrib.auth.decorators import login_required
from django.db.models import Q
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
        "downloads",
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
        "downloads",
        "status",
    ]
    max_display_length = 25

    def get_initial_queryset(self):
        return Dataset.objects.prefetch_related("users").all()

    def filter_queryset(self, qs):
        search = self.request.GET.get("search[value]")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(label__icontains=search)
                | Q(source__icontains=search)
                | Q(status__icontains=search)
            ).distinct()

        status_filter = self.request.GET.get("status")
        if status_filter in ["published", "private", "restricted", "under_review"]:
            qs = qs.filter(status=status_filter)

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
            status = row.status.replace("_", " ").title()
            status_badge_map = {
                "published": "badge-phoenix-success",
                "under_review": "badge-phoenix-primary",
                "private": "badge-phoenix-danger",
                "restricted": "badge-phoenix-warning",
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
    qs = Dataset.objects.all()
    counts = {
        "all": qs.count(),
        "published": qs.filter(status="published").count(),
        "private": qs.filter(status="private").count(),
        "restricted": qs.filter(status="restricted").count(),
        "under_review": qs.filter(status="under_review").count(),
    }
    status_filter = request.GET.get("status")

    return render(
        request,
        "datasets/datasets-list.html",
        {
            "dataset_num": counts,
            "status_filter": status_filter,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )
