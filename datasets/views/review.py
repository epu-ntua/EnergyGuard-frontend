"""Publication review of user datasets (reviewers only).

Gated by the 'datasets.review_dataset' permission - grant it via a Group
(e.g. "Dataset Reviewers") in the Django admin.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..models import REVIEW_PERMISSION, Dataset
from ..services.review import ReviewError, approve_dataset, reject_dataset

review_permission_required = permission_required(REVIEW_PERMISSION, raise_exception=True)

PAGE_SIZE = 20


@login_required
@review_permission_required
def dataset_review_list(request):
    status = request.GET.get('status', Dataset.Status.UNDER_REVIEW)
    if status not in Dataset.Status.values:
        status = Dataset.Status.UNDER_REVIEW

    submitted = Dataset.objects.submitted_for_review()
    counts = submitted.aggregate(
        **{value: Count('pk', filter=Q(status=value)) for value in Dataset.Status.values},
    )
    status_tabs = [
        {'value': value, 'label': label, 'count': counts[value]}
        for value, label in Dataset.Status.choices
    ]

    if status == Dataset.Status.UNDER_REVIEW:
        # Longest waiting first.
        ordering = [F('submitted_at').asc(nulls_first=True)]
    else:
        # Latest decision first; a status set by hand (e.g. in the admin) has
        # no reviewed_at and goes last.
        ordering = [F('reviewed_at').desc(nulls_last=True)]
    datasets = (
        submitted.filter(status=status)
        .select_related('publisher', 'reviewed_by')
        .order_by(*ordering, 'pk')
    )
    page_obj = Paginator(datasets, PAGE_SIZE).get_page(request.GET.get('page'))

    return render(
        request,
        'datasets/dataset-review-list.html',
        {
            'page_obj': page_obj,
            'status_tabs': status_tabs,
            'status_filter': status,
            'active_navbar_page': 'dataset_review',
            'show_sidebar': True,
        },
    )


@login_required
@review_permission_required
@require_POST
def dataset_approve(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)
    try:
        approve_dataset(dataset, actor=request.user, version=request.POST.get('version'))
    except ReviewError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Dataset "{dataset.name}" approved and published.')
    return redirect('dataset_details', dataset_id=dataset.pk)


@login_required
@review_permission_required
@require_POST
def dataset_reject(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)
    try:
        reject_dataset(
            dataset,
            actor=request.user,
            version=request.POST.get('version'),
            reason=request.POST.get('rejection_reason', ''),
        )
    except ReviewError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f'Dataset "{dataset.name}" rejected. The publisher has been notified.')
    return redirect('dataset_details', dataset_id=dataset.pk)
