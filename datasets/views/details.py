import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from projects.models import Project
from ..forms import GeneralDatasetForm
from ..models import REVIEW_PERMISSION, Dataset
from ..services.review import REJECTION_REASON_MAX_LENGTH


# Keys of ``metadata`` that describe the dataset itself rather than one of its
# features (see datasets.services.pilot.pilot_partner_for).
DATASET_LEVEL_METADATA_KEYS = frozenset({"pilot_partner"})


def _metadata_cell(value):
    """One cell as text. Nested JSON stays JSON, not a Python repr."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def metadata_table(metadata):
    """
    Turn a dataset's ``metadata`` into rows for the details page.

    Each feature is stored as ``{"name": [unit, description, data_type, valid_range]}``.
    The last two are optional (only the pilot datasets carry them), so a list of two
    is still a full row. The pilot metadata is written by hand in SQL, so an entry
    that is not a list is still shown, as its description, instead of disappearing.

    Rows are sorted by name: Postgres stores ``metadata`` as jsonb, which keeps keys
    ordered by length rather than in the order they were written.
    """
    rows = []
    if isinstance(metadata, dict):
        for name, value in sorted(metadata.items(), key=lambda item: item[0].casefold()):
            if name in DATASET_LEVEL_METADATA_KEYS:
                continue
            if isinstance(value, list):
                cells = [_metadata_cell(cell) for cell in value[:4]]
            else:
                cells = ["", _metadata_cell(value)]
            cells += [""] * (4 - len(cells))
            unit, description, data_type, valid_range = cells
            rows.append({
                "name": name,
                "unit": unit,
                "description": description,
                "data_type": data_type,
                "valid_range": valid_range,
            })
    return {
        "rows": rows,
        # Columns appear only when some feature fills them, so datasets uploaded
        # with unit and description only look the same as before.
        "has_data_type": any(row["data_type"] for row in rows),
        "has_valid_range": any(row["valid_range"] for row in rows),
    }


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
        "metadata": metadata_table(dataset.metadata),
    }

    user_projects = Project.objects.member_of(request.user).order_by("-created_at")

    # Platform-wide total, private projects included. Only projects the user
    # could open themselves are named.
    usage_total = dataset.projects.count()
    usage_projects = list(dataset.projects.visible_to(request.user).order_by("name"))

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
            "usage_projects": usage_projects,
            "usage_hidden": usage_total - len(usage_projects),
            "review": review,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )
