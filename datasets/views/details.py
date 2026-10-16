from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render

from projects.models import Project
from ..forms import GeneralDatasetForm
from ..models import REVIEW_PERMISSION, Dataset
from ..services.review import REJECTION_REASON_MAX_LENGTH


@login_required
def dataset_details(request, dataset_id):
    try:
        dataset = Dataset.objects.visible_to(request.user).select_related("reviewed_by").get(pk=dataset_id)
    except Dataset.DoesNotExist:
        # Deliberately indistinguishable from "does not exist" so the response
        # does not confirm that a private dataset with this id is out there.
        messages.error(request, "Dataset not found")
        return redirect("home")

    dataset_details_data = {
        "id": dataset.id,
        "name": dataset.name,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "status": dataset.status,
        "label": dataset.get_label_display(),
        "source": dataset.get_source_display(),
        "visibility": dataset.visibility,
        "size": dataset.size_gb,
        "publisher": dataset.publisher_display,
        "description": dataset.description,
        "metadata": dataset.metadata,
    }

    user_projects = Project.objects.filter(
        Q(creator=request.user) | Q(collaborators=request.user)
    ).distinct().order_by("-created_at")

    # Platform-wide total, private projects included. Only a number, so no
    # project names are exposed.
    usage_total = dataset.projects.count()

    # Review state is shown to the publisher and reviewers of a user dataset
    # submitted for publication; other viewers only ever see it published.
    can_review = request.user.has_perm(REVIEW_PERMISSION)
    review_alerts = {
        Dataset.Status.UNDER_REVIEW: ("warning", "fa-hourglass-half"),
        Dataset.Status.REJECTED: ("danger", "fa-circle-xmark"),
        Dataset.Status.APPROVED: ("success", "fa-circle-check"),
    }
    alert_class, icon = review_alerts[dataset.status]
    review = {
        "show": bool(
            dataset.visibility
            and dataset.publisher_id
            and (can_review or dataset.publisher_id == request.user.id)
            # An approved dataset needs no banner for its publisher.
            and (dataset.status != Dataset.Status.APPROVED or can_review)
        ),
        "can_review": can_review,
        "alert_class": alert_class,
        "icon": icon,
        "reason_max_length": REJECTION_REASON_MAX_LENGTH,
    }

    return render(
        request,
        "datasets/dataset-details.html",
        {
            "dataset": dataset,
            "dt": dataset_details_data,
            "edit_form": GeneralDatasetForm(instance=dataset),
            "user_projects": user_projects,
            "usage_total": usage_total,
            "review": review,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )
