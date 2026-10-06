from collections import Counter

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render

from accounts.models import Profile
from core.views.ai_models import AI_MODELS, CATEGORY_LABELS
from datasets.models import Dataset
from digitaltwins.views import DIGITAL_TWINS
from projects.models import Project


# TODO: replace with a real availability flag on each entry of DIGITAL_TWINS.
DIGITAL_TWINS_AVAILABLE_COUNT = 5


@login_required
def dashboard(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    team = profile.team

    # TODO: update this to the team's projects once teams are properly implemented (Project has
    # no team FK any more, and creator__profile__team returns nothing for users without a team).
    user_projects_count = Project.objects.filter(creator=request.user).count()
    # Same query as the "Public" tab of the projects list, so the numbers match.
    public_projects_count = Project.objects.filter(visibility=True).exclude(creator=request.user).count()

    # Same query as the "Public" tab of the datasets list, so the numbers match.
    datasets_count = Dataset.objects.filter(visibility=True).exclude(publisher=request.user).count()
    # Same query as the "My" tab of the datasets list.
    user_datasets_count = Dataset.objects.filter(publisher=request.user).count()

    # The charts only include "available" datasets: public ones that are either platform-owned or approved.
    # TODO: implement the dataset review workflow. Until then user-published datasets stay
    # "under review" and are only counted as available once someone approves them manually.
    available_datasets = Dataset.objects.filter(visibility=True).filter(
        Q(publisher__isnull=True) | Q(status=Dataset.Status.APPROVED)
    )

    ai_models_badges = Counter(model["badge"] for model in AI_MODELS)
    ai_models_count = ai_models_badges.get("available", 0)
    ai_models_on_request_count = ai_models_badges.get("request_access", 0)
    ai_models_coming_soon_count = ai_models_badges.get("coming_soon", 0)

    digital_twins_total = len(DIGITAL_TWINS)
    digital_twins_count = min(DIGITAL_TWINS_AVAILABLE_COUNT, digital_twins_total)
    digital_twins_in_preparation_count = digital_twins_total - digital_twins_count

    datasets_counts_by_label = {
        row["label"]: row["total"]
        for row in available_datasets.values("label").annotate(total=Count("id"))
    }

    datasets_chart_data = [
        {
            "category": label_display,
            "value": datasets_counts_by_label.get(label_value, 0),
        }
        for label_value, label_display in Dataset.Label.choices
    ]
    datasets_chart_data.sort(key=lambda item: item["value"], reverse=True)

    ai_models_by_category = Counter(
        model["category"] for model in AI_MODELS if model["badge"] == "available"
    )
    ai_models_chart_data = [
        {"category": label, "value": ai_models_by_category.get(category_key, 0)}
        for category_key, label in CATEGORY_LABELS.items()
        if ai_models_by_category.get(category_key, 0) > 0
    ]
    ai_models_chart_data.sort(key=lambda item: item["value"], reverse=True)

    return render(
        request,
        "core/dashboard.html",
        {
            "active_navbar_page": "dashboard",
            "show_sidebar": True,
            "chart_data": datasets_chart_data,
            "ai_models_chart_data": ai_models_chart_data,
            "projects_count": user_projects_count,
            "public_projects_count": public_projects_count,
            "datasets_count": datasets_count,
            "user_datasets_count": user_datasets_count,
            "ai_models_count": ai_models_count,
            "ai_models_on_request_count": ai_models_on_request_count,
            "ai_models_coming_soon_count": ai_models_coming_soon_count,
            "digital_twins_count": digital_twins_count,
            "digital_twins_total": digital_twins_total,
            "digital_twins_in_preparation_count": digital_twins_in_preparation_count,
            "team": team,
        },
    )
