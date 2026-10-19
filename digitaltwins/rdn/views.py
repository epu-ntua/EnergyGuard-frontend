import json
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.services.object_storage import MinioUploadError
from digitaltwins.common import RUNS_PAGE_SIZE, check_rate_limit, dt_render, format_duration, iter_body_chunks
from digitaltwins.models import RdnSimulationJob

from .services.client import RdnApiError, upload_rdn_input
from .services.results import open_result_stream
from .tasks import start_polling
from .validation import (
    MAX_ASSETS,
    MAX_SETPOINTS,
    RDN_ASSET_TYPES,
    RDN_GRID_SECTIONS,
    RDN_LOCKED_USE_CASES,
    RDN_USE_CASES,
    validate_rdn_grid_input,
)

logger = logging.getLogger(__name__)

_SIMULATE_RATE_LIMIT = 5  # lower than the default: real RDN jobs are far heavier than a typical request
_SIMULATE_RATE_WINDOW = 60


@login_required
def rdn_grid_dt(request):
    return dt_render(
        request, 'digitaltwins/rdn-grid-dt.html',
        use_cases=RDN_USE_CASES,
        locked_use_cases=RDN_LOCKED_USE_CASES,
        grid_sections=RDN_GRID_SECTIONS,
        asset_types=RDN_ASSET_TYPES,
        max_assets=MAX_ASSETS,
        max_setpoints=MAX_SETPOINTS,
    )


def _job_duration_label(job):
    end = job.updated_at if job.status in (RdnSimulationJob.Status.COMPLETED, RdnSimulationJob.Status.FAILED) else datetime.now(timezone.utc)
    if job.status in (RdnSimulationJob.Status.COMPLETED, RdnSimulationJob.Status.FAILED) and (end - job.created_at).total_seconds() < 1:
        # updated_at was only ever refreshed on terminal transitions starting with this
        # feature - a job that finished before that fix has updated_at == created_at,
        # so treat a sub-second "duration" as unknown rather than showing a false 0s.
        return '—'
    return format_duration((end - job.created_at).total_seconds())


@login_required
def rdn_grid_runs(request):
    # .defer('result'): legacy runs still carry their full payload inline in this column
    # (see RdnSimulationJob.result) - hundreds of MB for old large runs - which this listing
    # never displays, so fetching it here would be pure wasted I/O.
    jobs = RdnSimulationJob.objects.filter(user=request.user).defer('result').order_by('-created_at')
    paginator = Paginator(jobs, RUNS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    for job in page_obj:
        job.duration_label = _job_duration_label(job)
        job.use_case_label = RDN_USE_CASES.get(job.use_case, job.use_case)

    return dt_render(request, 'digitaltwins/rdn-grid-runs.html', page_obj=page_obj)


def _assets_breakdown(assets_items):
    counts = {}
    for _, asset_type in assets_items:
        counts[asset_type] = counts.get(asset_type, 0) + 1
    return ' · '.join(f'{count} {asset_type}' for asset_type, count in counts.items())


@login_required
def rdn_grid_results(request, rdn_request_id):
    job = get_object_or_404(RdnSimulationJob, rdn_request_id=rdn_request_id, user=request.user)
    # job.assets is the asset_NNN -> assetType mapping the user actually submitted (set at
    # creation, unrelated to run status). RDN's own output (job.result[...]['grid']) is a
    # different thing - the full bus list of the section's fixed topology (RDN simulates
    # every bus in the section, not just the ones the user supplied setpoints for), so it
    # is NOT used here even for completed runs - "Configuration Used" means what was
    # submitted, not what RDN internally modeled.
    assets_items = sorted(job.assets.items())
    return dt_render(
        request, 'digitaltwins/rdn-grid-results.html',
        job=job,
        use_case_label=RDN_USE_CASES.get(job.use_case, job.use_case),
        duration_label=_job_duration_label(job),
        assets_items=assets_items,
        assets_breakdown=_assets_breakdown(assets_items),
        # The payload is fetched separately rather than inlined into the page:
        # an RDN result can run to hundreds of megabytes, which is not something
        # to embed in HTML.
        result_url=reverse('rdn-grid-result-data', args=[job.rdn_request_id]),
        has_result=job.has_result,
    )


@login_required
def rdn_grid_result_data(request, rdn_request_id):
    """Stream a completed run's result JSON, scoped to its owner."""
    job = get_object_or_404(RdnSimulationJob, rdn_request_id=rdn_request_id, user=request.user)

    if job.status != RdnSimulationJob.Status.COMPLETED or not job.has_result:
        return JsonResponse({'error': 'This run has no result yet.'}, status=404)

    if not job.result_key:
        # Completed before results moved to object storage - still in the column.
        response = JsonResponse(job.result, safe=False)
    else:
        try:
            body, content_length = open_result_stream(job.result_key)
        except MinioUploadError:
            logger.exception('Could not read RDN result for request %s', rdn_request_id)
            return JsonResponse({'error': 'The result could not be retrieved.'}, status=502)

        response = StreamingHttpResponse(iter_body_chunks(body), content_type='application/json')
        if content_length is not None:
            response['Content-Length'] = content_length

    if request.GET.get('download'):
        response['Content-Disposition'] = f'attachment; filename="rdn-grid-result-{rdn_request_id}.json"'
    return response


@login_required
@require_POST
def rdn_grid_run_delete(request, rdn_request_id):
    """Delete one of the user's finished runs and its result.

    Only completed or failed runs: while one is pending or running the poll chain
    is still waiting on RDN, and deleting it would not cancel anything there. A
    deleted run can no longer be continued, since the follow-up lookup reads it.
    """
    # .defer('result'): a legacy run's inline payload can be hundreds of MB, and
    # deleting the row does not need it.
    job = get_object_or_404(
        RdnSimulationJob.objects.defer('result'), rdn_request_id=rdn_request_id, user=request.user,
        status__in=(RdnSimulationJob.Status.COMPLETED, RdnSimulationJob.Status.FAILED),
    )
    # Its stored result and JupyterHub copies follow it (digitaltwins.signals).
    job.delete()
    return redirect('rdn-grid-runs')


@login_required
@require_POST
def rdn_grid_simulate(request):
    if not check_rate_limit(request.user.pk, 'rdn_grid', _SIMULATE_RATE_LIMIT, _SIMULATE_RATE_WINDOW):
        return JsonResponse({'error': 'Too many requests. Please wait before running another simulation.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    cleaned, error = validate_rdn_grid_input(body)
    if error:
        return JsonResponse({'error': error}, status=400)

    job = RdnSimulationJob.objects.create(
        user=request.user,
        use_case=cleaned['useCase'],
        grid_section=cleaned['inputData']['gridSection'],
        assets={aid: a['assetType'] for aid, a in cleaned['inputData']['asset'].items()},
    )
    job.rdn_request_id = job.pk
    job.save(update_fields=['rdn_request_id'])

    # userId/userOrganisation are the single shared EnergyGuard service account, never
    # the platform user's own identity - see [[project_rdn_api_integration]] design.
    payload = {
        'userId': settings.RDN_API_USER_ID,
        'userOrganisation': settings.RDN_API_ORGANISATION,
        'useCase': cleaned['useCase'],
        'requestId': job.rdn_request_id,
        'requestTimestamp_UTC': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'followsRequestId': cleaned['followsRequestId'],
        'inputData': cleaned['inputData'],
    }

    try:
        upload_rdn_input(payload)
    except RdnApiError as exc:
        logger.exception('RDN upload failed for job %s', job.pk)
        RdnSimulationJob.objects.filter(pk=job.pk).update(
            status=RdnSimulationJob.Status.FAILED, error_message=str(exc), updated_at=datetime.now(timezone.utc),
        )
        return JsonResponse({'error': 'Could not submit the request to RDN.'}, status=502)

    try:
        start_polling(job)
    except DatabaseError:
        # RDN already has the input and will run it, so this is not a failed
        # request: the job stays pending, and the hourly reconcile task starts
        # polling it (see reconcile_stale_rdn_jobs). The results page treats
        # pending like running, so the user just waits a little longer.
        logger.exception('Could not start polling RDN job %s; reconcile will pick it up', job.pk)
        return JsonResponse(
            {'jobId': job.pk, 'requestId': job.rdn_request_id, 'status': RdnSimulationJob.Status.PENDING},
            status=202,
        )

    return JsonResponse(
        {'jobId': job.pk, 'requestId': job.rdn_request_id, 'status': RdnSimulationJob.Status.RUNNING},
        status=202,
    )


@login_required
def rdn_grid_job_status(request):
    try:
        job_id = int(request.GET.get('job', ''))
    except ValueError:
        return JsonResponse({'error': 'Invalid job id.'}, status=400)

    job = RdnSimulationJob.objects.filter(pk=job_id, user=request.user).first()
    if job is None:
        return JsonResponse({'error': 'Not found.'}, status=404)

    payload = {'status': job.status, 'requestId': job.rdn_request_id}
    if job.status == RdnSimulationJob.Status.COMPLETED:
        # A URL, not the payload: this endpoint is polled every 10s, and
        # re-serialising a multi-hundred-megabyte result each time is pure waste.
        payload['resultUrl'] = reverse('rdn-grid-result-data', args=[job.rdn_request_id])
    elif job.status == RdnSimulationJob.Status.FAILED:
        payload['error'] = job.error_message
    return JsonResponse(payload)


@login_required
def rdn_grid_follow_lookup(request):
    try:
        request_id = int(request.GET.get('requestId', ''))
    except ValueError:
        return JsonResponse({'error': 'Invalid requestId.'}, status=400)

    job = RdnSimulationJob.objects.filter(
        pk=request_id, user=request.user, status=RdnSimulationJob.Status.COMPLETED,
    ).first()
    if job is None:
        return JsonResponse({'found': False})

    return JsonResponse({'found': True, 'gridSection': job.grid_section, 'useCase': job.use_case, 'assets': job.assets})
