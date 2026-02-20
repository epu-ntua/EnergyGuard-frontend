from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from datasets.models import Dataset
from projects.models import Project


@login_required
def dashboard(request):
    projects_count = Project.objects.count()
    datasets_count = Dataset.objects.filter(publisher__isnull=True).count()

    datasets_counts_by_label = {
        row["label"]: row["total"]
        for row in Dataset.objects.filter(publisher__isnull=True)
        .values("label")
        .annotate(total=Count("id"))
    }

    datasets_chart_data = [
        {
            "category": label_display,
            "value": datasets_counts_by_label.get(label_value, 0),
        }
        for label_value, label_display in Dataset.Label.choices
    ]
    datasets_chart_data.sort(key=lambda item: item["value"], reverse=True)

    return render(
        request,
        "core/dashboard.html",
        {
            "active_navbar_page": "dashboard",
            "show_sidebar": True,
            "chart_data": datasets_chart_data,
            "projects_count": projects_count,
            "datasets_count": datasets_count,
        },
    )
