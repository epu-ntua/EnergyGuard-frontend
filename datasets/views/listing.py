from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import CharField, Count, F, Q, Value
from django.db.models.functions import Coalesce, Concat, Lower, NullIf, Trim
from django.shortcuts import render
from django_datatables_view.base_datatable_view import BaseDatatableView

from ..models import Dataset


class DatasetsListJson(LoginRequiredMixin, BaseDatatableView):
    model = Dataset
    columns = [
        "name",
        "created_at",
        "label",
        "source",
        "publisher",
        "size_gb",
        "projects_count",
        # Publication state; only the "My" tab shows it.
        "status",
        "id",
    ]
    order_columns = [
        "name",
        "created_at",
        "label",
        "source",
        # Sort by the name the column shows, not the publisher FK id.
        "publisher_sort",
        "size_gb",
        "projects_count",
    ]
    max_display_length = 25

    def get_initial_queryset(self):
        return Dataset.objects.annotate(
            projects_count=Count("projects", distinct=True),
            # Mirrors Dataset.publisher_display: full name, else email, else
            # the platform name for publisher-less (pilot) datasets.
            publisher_sort=Lower(Coalesce(
                NullIf(Trim(Concat(
                    F("publisher__first_name"), Value(" "), F("publisher__last_name"),
                )), Value("")),
                F("publisher__email"),
                Value(Dataset.PLATFORM_PUBLISHER),
                output_field=CharField(),
            )),
        )

    def ordering(self, qs):
        qs = super().ordering(qs)
        # The table pages server-side, and label/publisher/usage tie on most
        # rows: without a unique last key, rows repeat or vanish across pages.
        if qs.query.order_by:
            qs = qs.order_by(*qs.query.order_by, "id")
        return qs

    def filter_queryset(self, qs):
        scope = self.request.GET.get("scope", "public")
        if scope == "my":
            qs = qs.filter(publisher=self.request.user)
        else:
            qs = qs.published()

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
            if self.request.GET.get("scope") != "my":
                return ""
            if not row.visibility:
                return "private"
            return "published" if row.is_published else row.status
        return super().render_column(row, column)


@login_required
def datasets_list(request):
    my_qs = Dataset.objects.filter(publisher=request.user)
    public_qs = Dataset.objects.published()

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
