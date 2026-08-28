from collections import Counter

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from accounts.models import Profile
from core.views.ai_models import AI_MODELS, CATEGORY_LABELS
from datasets.models import Dataset
from digitaltwins.views import DIGITAL_TWINS
from projects.models import Project


@login_required
def dashboard(request):
    projects_count = Project.objects.count()
    datasets_count = Dataset.objects.filter(publisher__isnull=True).count()
    ai_models_count = len(AI_MODELS)
    digital_twins_count = len(DIGITAL_TWINS)

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

    ai_models_by_category = Counter(model["category"] for model in AI_MODELS)
    ai_models_chart_data = [
        {"category": label, "value": ai_models_by_category.get(category_key, 0)}
        for category_key, label in CATEGORY_LABELS.items()
        if ai_models_by_category.get(category_key, 0) > 0
    ]
    ai_models_chart_data.sort(key=lambda item: item["value"], reverse=True)

    profile, _ = Profile.objects.get_or_create(user=request.user)

    return render(
        request,
        "core/dashboard.html",
        {
            "active_navbar_page": "dashboard",
            "show_sidebar": True,
            "chart_data": datasets_chart_data,
            "ai_models_chart_data": ai_models_chart_data,
            "projects_count": projects_count,
            "datasets_count": datasets_count,
            "ai_models_count": ai_models_count,
            "digital_twins_count": digital_twins_count,
            "team": profile.team,
        },
    )
