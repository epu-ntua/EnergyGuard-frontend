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
        return Dataset.objects.all()

    def filter_queryset(self, qs):
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
    qs = Dataset.objects.all()
    label_filter = request.GET.get("label")
    allowed_labels = [value for value, _ in Dataset.Label.choices]
    if label_filter not in allowed_labels:
        label_filter = None

    label_tabs = [
        {
            "value": value,
            "display": display,
            "count": qs.filter(label=value).count(),
        }
        for value, display in Dataset.Label.choices
    ]

    return render(
        request,
        "datasets/datasets-list.html",
        {
            "dataset_num": {"all": qs.count()},
            "label_filter": label_filter,
            "label_tabs": label_tabs,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )
