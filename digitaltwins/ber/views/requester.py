"""BER experiment requests, from the requester's side: submit, list, follow, view results."""

import hashlib
import json
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from core.services.object_storage import MinioUploadError
from digitaltwins.common import check_rate_limit, dt_render
from digitaltwins.models import BerExperimentRequest

from ..services.results import BER_SIGNAL_INFO, BerResultUnreadable, build_ber_results_context
from ..services.validation import validate_ber_experiment
from .shared import PAGE_SIZE, result_file_response

logger = logging.getLogger(__name__)

BER_VALIDATION_CHECKS = [
    'Valid JSON format',
    'Required commands present',
    'Time values are progressive',
    'Control mode is valid',
    'Regeneration mode is valid',
    'Setpoints within allowed range',
    'Total experiment duration does not exceed 8 hours (28.800 seconds)',
]

BER_SAMPLE_JSON = """[
    {
        "time": 0,
        "command": "set_control_mode",
        "value": "amp"
    },
    {
        "time": 1,
        "command": "set_regen_mode",
        "value": "instant"
    },
    {
        "time": 60,
        "command": "change_setpoint",
        "value": "20"
    },
    {
        "time": 300,
        "command": "change_setpoint",
        "value": "40"
    }
]"""

# Lower than the default: each submission notifies the real BER lab team by email,
# unlike a typical simulate call.
_SUBMIT_RATE_LIMIT = 5
_SUBMIT_RATE_WINDOW = 60

# A client retry (lost/ambiguous response) within this window, with the exact same
# validated content from the same user, returns the original request instead of
# creating a duplicate row and a duplicate BER notification email.
_SUBMIT_DEDUP_WINDOW_SECONDS = 30


def _submit_dedup_key(user_id, cleaned):
    digest = hashlib.sha256(json.dumps(cleaned, sort_keys=True).encode()).hexdigest()
    return f'ber_submit_dedup_{user_id}_{digest}'


@login_required
def ber_hydrogen_dt(request):
    return dt_render(request, 'digitaltwins/ber-hydrogen-dt.html',
                     validation_checks=BER_VALIDATION_CHECKS, sample_json=BER_SAMPLE_JSON)


@login_required
def ber_hydrogen_documentation(request):
    return dt_render(request, 'digitaltwins/ber-hydrogen-documentation.html', sample_json=BER_SAMPLE_JSON)


@login_required
@require_POST
def ber_experiment_submit(request):
    if not check_rate_limit(request.user.pk, 'ber_experiment', _SUBMIT_RATE_LIMIT, _SUBMIT_RATE_WINDOW):
        return JsonResponse({'error': 'Too many requests. Please wait before submitting another experiment.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    cleaned, error = validate_ber_experiment(body)
    if error:
        return JsonResponse({'error': error}, status=400)

    dedup_key = _submit_dedup_key(request.user.pk, cleaned)
    existing_id = cache.get(dedup_key)
    if existing_id is not None:
        existing_request = BerExperimentRequest.objects.filter(pk=existing_id).first()
        if existing_request is not None:
            return JsonResponse(
                {'requestId': existing_request.pk, 'status': existing_request.status}, status=202,
            )

    experiment_request = BerExperimentRequest.objects.create(user=request.user, experiment_json=cleaned)
    cache.set(dedup_key, experiment_request.pk, timeout=_SUBMIT_DEDUP_WINDOW_SECONDS)

    if settings.BER_EMAIL:
        async_task(
            'digitaltwins.ber.tasks.send_ber_notification_email',
            experiment_request.pk, request.build_absolute_uri('/'),
        )

    return JsonResponse(
        {'requestId': experiment_request.pk, 'status': experiment_request.status}, status=202,
    )


@login_required
def ber_hydrogen_runs(request):
    experiment_requests = BerExperimentRequest.objects.filter(user=request.user, hidden_by_user_at__isnull=True).order_by('-created_at')
    paginator = Paginator(experiment_requests, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))
    return dt_render(request, 'digitaltwins/ber-hydrogen-runs.html', page_obj=page_obj)


def _render_results(request, experiment_request):
    def _unavailable(message):
        return dt_render(
            request, 'digitaltwins/ber-hydrogen-request-detail.html',
            experiment_request=experiment_request, result_error=message,
        )

    if not experiment_request.result_key:
        return _unavailable('This experiment has been completed, but its result file is not available yet.')

    try:
        context = build_ber_results_context(experiment_request)
    except MinioUploadError:
        logger.exception('Could not read BER result file for request %s', experiment_request.pk)
        return _unavailable('The results could not be loaded right now. Please try again later.')
    except BerResultUnreadable:
        logger.exception('BER result file for request %s has no usable data', experiment_request.pk)
        return _unavailable('The result file for this experiment could not be read. Please contact the BER laboratory team.')

    return dt_render(
        request, 'digitaltwins/ber-hydrogen-results.html',
        experiment_request=experiment_request, signal_info=BER_SIGNAL_INFO, **context,
    )


@login_required
def ber_hydrogen_request_detail(request, request_id):
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id, user=request.user)
    if experiment_request.status == BerExperimentRequest.Status.COMPLETED:
        return _render_results(request, experiment_request)
    return dt_render(
        request, 'digitaltwins/ber-hydrogen-request-detail.html', experiment_request=experiment_request,
    )


@login_required
def ber_hydrogen_request_result_download(request, request_id):
    """Stream the requester's own completed result file."""
    experiment_request = get_object_or_404(
        BerExperimentRequest, pk=request_id, user=request.user, status=BerExperimentRequest.Status.COMPLETED,
    )
    return result_file_response(experiment_request)


@login_required
@require_POST
def ber_hydrogen_request_cancel(request, request_id):
    """Requester withdraws a pending request; BER staff are notified so they don't run it."""
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id, user=request.user)
    now = datetime.now(timezone.utc)

    # Conditional on PENDING: if BER decided it a moment earlier, the decision stands.
    cancelled = BerExperimentRequest.objects.filter(
        pk=experiment_request.pk, status=BerExperimentRequest.Status.PENDING,
    ).update(status=BerExperimentRequest.Status.CANCELLED, cancelled_at=now, updated_at=now)

    if cancelled and settings.BER_EMAIL:
        async_task(
            'digitaltwins.ber.tasks.send_ber_cancellation_email',
            experiment_request.pk, request.build_absolute_uri('/'),
        )
    return redirect('ber-hydrogen-request-detail', request_id=experiment_request.pk)


@login_required
@require_POST
def ber_hydrogen_request_hide(request, request_id):
    """Requester removes a finished request from their own list. BER staff still see it."""
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id, user=request.user)
    now = datetime.now(timezone.utc)

    BerExperimentRequest.objects.filter(
        pk=experiment_request.pk, hidden_by_user_at__isnull=True,
        status__in=BerExperimentRequest.FINISHED_STATUSES,
    ).update(hidden_by_user_at=now, updated_at=now)
    return redirect('ber-hydrogen-runs')


@login_required
def ber_hydrogen_request_status(request, request_id):
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id, user=request.user)
    return JsonResponse({'status': experiment_request.status})
