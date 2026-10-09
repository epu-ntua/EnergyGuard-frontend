"""BER experiment management (staff-only).

Gated by the 'digitaltwins.manage_ber_requests' permission - grant it via a
Group (e.g. "BER Team") assigned to the BER staff's own EnergyGuard accounts.
"""

import json
import logging
from datetime import datetime, timezone

from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from core.services.object_storage import MinioUploadError
from digitaltwins.common import dt_render, format_duration
from digitaltwins.models import BerExperimentRequest

from ..services.storage import delete_result_file, store_result_file
from ..upload_progress import UPLOAD_ID_RE, progress_callback_for, read_progress
from .shared import PAGE_SIZE, result_file_response, result_filename

logger = logging.getLogger(__name__)

_RESULT_FILE_MAX_SIZE_MB = 50  # real .lp signal logs, not the JSON request itself
_ARCHIVED_TAB = 'archived'

manage_permission_required = permission_required('digitaltwins.manage_ber_requests', raise_exception=True)


def _parse_datetime(raw):
    try:
        return datetime.strptime(raw, '%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _list_filters(params):
    """Status tab + page the staff member is on, carried through GET links and
    the panel's POST forms so a decision returns them to the same list view."""
    status = params.get('status', '')
    if status not in BerExperimentRequest.Status.values and status != _ARCHIVED_TAB:
        status = ''
    return status, params.get('page', '')


def _list_url(status, page, selected_id=None):
    query = {key: value for key, value in (('status', status), ('page', page), ('request', selected_id)) if value}
    url = reverse('ber-management-list')
    return f'{url}?{urlencode(query)}' if query else url


def _request_summary(experiment_request):
    commands = experiment_request.experiment_json or []
    duration = max((command.get('time', 0) for command in commands), default=0)
    json_size = len(json.dumps(commands, indent=2).encode())
    return {
        'command_count': len(commands),
        'duration_label': format_duration(duration),
        'json_filename': f'experiment_{experiment_request.pk}.json',
        'json_size_label': f'{json_size / 1024:.1f} KB',
        # Same name the download is served under (see result_file_response).
        'result_filename': result_filename(experiment_request) if experiment_request.result_key else '',
    }


def _panel_context(experiment_request, status, page, error=None):
    return {
        'selected': experiment_request,
        'selected_summary': _request_summary(experiment_request),
        'status_filter': status,
        'page_number': page,
        'error': error,
    }


def _render_management(request, params, selected=None, error=None):
    status, page = _list_filters(params)

    not_archived = Q(archived_at__isnull=True)
    counts = BerExperimentRequest.objects.aggregate(
        total=Count('pk', filter=not_archived),
        archived_total=Count('pk', filter=Q(archived_at__isnull=False)),
        **{value: Count('pk', filter=not_archived & Q(status=value)) for value in BerExperimentRequest.Status.values},
    )
    status_tabs = [{'value': '', 'label': 'All', 'count': counts['total']}] + [
        {'value': value, 'label': label, 'count': counts[value]}
        for value, label in BerExperimentRequest.Status.choices
    ] + [{'value': _ARCHIVED_TAB, 'label': 'Archived', 'count': counts['archived_total']}]
    for tab in status_tabs:
        tab['url'] = _list_url(tab['value'], '')

    experiment_requests = BerExperimentRequest.objects.select_related('user')
    if status == _ARCHIVED_TAB:
        experiment_requests = experiment_requests.filter(archived_at__isnull=False).order_by('-archived_at')
    else:
        experiment_requests = experiment_requests.filter(not_archived).order_by('-created_at')
        if status:
            experiment_requests = experiment_requests.filter(status=status)
    page_obj = Paginator(experiment_requests, PAGE_SIZE).get_page(page)

    context = {'page_obj': page_obj, 'status_tabs': status_tabs}
    if selected is not None:
        context.update(_panel_context(selected, status, page_obj.number, error))
    else:
        context.update({'status_filter': status, 'page_number': page_obj.number})
    return dt_render(request, 'digitaltwins/ber-management-list.html', active_navbar_page='ber_management', **context)


def _discard_result_file(object_key, request_id, reason):
    """Best-effort removal of a result file nothing points to any more. A failure
    only leaves an orphaned object, so it is logged (with the key, for manual
    cleanup) rather than surfaced to the staff member."""
    try:
        delete_result_file(object_key)
    except MinioUploadError:
        logger.exception('Could not delete BER result file %s for request %s (%s)', object_key, request_id, reason)


def _validate_result_file(result_file):
    if not result_file:
        return 'Choose a result file to upload.'
    if result_file.size > _RESULT_FILE_MAX_SIZE_MB * 1024 * 1024:
        return f'Result file exceeds the {_RESULT_FILE_MAX_SIZE_MB} MB limit.'
    return None


def _wants_json(request):
    """The panel's upload forms are sent by XHR (for the progress bar); they get
    JSON back, while the plain form submit (no JS) keeps the normal page flow."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _done(request, next_url):
    if _wants_json(request):
        return JsonResponse({'redirect': next_url})
    return redirect(next_url)


def _not_pending_message(experiment_request):
    if experiment_request.status == BerExperimentRequest.Status.CANCELLED:
        return 'The requester cancelled this request.'
    return 'This request has already been decided.'


@login_required
@manage_permission_required
def ber_management_list(request):
    selected = None
    selected_id = request.GET.get('request', '')
    if selected_id.isdigit():
        selected = BerExperimentRequest.objects.select_related('user', 'archived_by').filter(pk=selected_id).first()
    return _render_management(request, request.GET, selected=selected)


@login_required
@manage_permission_required
def ber_management_panel(request, request_id):
    """Side-panel fragment fetched by the list page when a row is clicked."""
    experiment_request = get_object_or_404(BerExperimentRequest.objects.select_related('user', 'archived_by'), pk=request_id)
    status, page = _list_filters(request.GET)
    return render(
        request, 'digitaltwins/partials/ber-management-panel.html',
        _panel_context(experiment_request, status, page),
    )


@login_required
@manage_permission_required
def ber_management_detail(request, request_id):
    """GET (e.g. the link in the BER notification email) opens the list with this
    request's panel; POST marks the request completed or rejected."""
    experiment_request = get_object_or_404(BerExperimentRequest.objects.select_related('user'), pk=request_id)

    if request.method != 'POST':
        return redirect(_list_url('', '', experiment_request.pk))

    status, page = _list_filters(request.POST)

    def _error(message):
        if _wants_json(request):
            return JsonResponse({'error': message}, status=400)
        return _render_management(request, request.POST, selected=experiment_request, error=message)

    if experiment_request.status != BerExperimentRequest.Status.PENDING:
        return _error(_not_pending_message(experiment_request))

    action = request.POST.get('action')
    now = datetime.now(timezone.utc)
    pending = BerExperimentRequest.objects.filter(pk=experiment_request.pk, status=BerExperimentRequest.Status.PENDING)

    if action == 'complete':
        result_file = request.FILES.get('result_file')
        actual_start = _parse_datetime(request.POST.get('actual_start', ''))
        actual_end = _parse_datetime(request.POST.get('actual_end', ''))

        if actual_start is None or actual_end is None:
            return _error('Provide a valid start and end time.')
        if actual_end <= actual_start:
            return _error('End time must be after start time.')
        file_error = _validate_result_file(result_file)
        if file_error:
            return _error(file_error)

        try:
            result_key = store_result_file(
                experiment_request.pk, result_file,
                progress_callback=progress_callback_for(request, result_file),
            )
        except MinioUploadError:
            logger.exception('Failed to store BER result file for request %s', experiment_request.pk)
            return _error('Could not store the result file. Please try again.')

        # Conditional update: two staff members deciding the same request at once
        # must not both succeed (and both notify the requester).
        updated = pending.update(
            actual_start=actual_start, actual_end=actual_end, result_key=result_key,
            status=BerExperimentRequest.Status.COMPLETED, updated_at=now,
        )
        if not updated:
            _discard_result_file(result_key, experiment_request.pk, 'request was decided concurrently')

    elif action == 'reject':
        reason = request.POST.get('rejection_reason', '').strip()
        if not reason:
            return _error('A rejection reason is required.')
        updated = pending.update(
            rejection_reason=reason, status=BerExperimentRequest.Status.REJECTED, updated_at=now,
        )

    else:
        return JsonResponse({'error': 'Invalid action.'}, status=400)

    if not updated:
        experiment_request.refresh_from_db()
        return _error(_not_pending_message(experiment_request))

    if action == 'complete':
        async_task('digitaltwins.ber.tasks.warm_ber_results_cache', experiment_request.pk)
    async_task(
        'digitaltwins.ber.tasks.notify_ber_request_decision',
        experiment_request.pk, request.build_absolute_uri('/'),
    )
    return _done(request, _list_url(status, page, experiment_request.pk))


@login_required
@manage_permission_required
@require_POST
def ber_management_replace_result(request, request_id):
    """Swap a completed request's result file (e.g. the wrong file was uploaded).

    Order matters: the new file goes to a fresh key, the row is switched to it, and
    only then is the old file deleted - so the request always points to a complete
    file. The new key also changes the results cache key, so the requester sees the
    new data immediately.
    """
    experiment_request = get_object_or_404(BerExperimentRequest.objects.select_related('user', 'archived_by'), pk=request_id)
    status, page = _list_filters(request.POST)

    def _error(message):
        if _wants_json(request):
            return JsonResponse({'error': message}, status=400)
        return _render_management(request, request.POST, selected=experiment_request, error=message)

    if experiment_request.status != BerExperimentRequest.Status.COMPLETED:
        return _error('Only completed requests have a result file to replace.')

    result_file = request.FILES.get('result_file')
    file_error = _validate_result_file(result_file)
    if file_error:
        return _error(file_error)

    old_key = experiment_request.result_key
    try:
        new_key = store_result_file(
            experiment_request.pk, result_file,
            progress_callback=progress_callback_for(request, result_file),
        )
    except MinioUploadError:
        logger.exception('Failed to store replacement BER result file for request %s', experiment_request.pk)
        return _error('Could not store the result file. Please try again.')

    # Conditional on the key we read: if another staff member replaced it meanwhile,
    # theirs stands and this upload is discarded.
    now = datetime.now(timezone.utc)
    switched = BerExperimentRequest.objects.filter(
        pk=experiment_request.pk, status=BerExperimentRequest.Status.COMPLETED, result_key=old_key,
    ).update(result_key=new_key, updated_at=now)

    if not switched:
        _discard_result_file(new_key, experiment_request.pk, 'result was replaced concurrently')
        experiment_request.refresh_from_db()
        return _error('The result file was changed by someone else in the meantime. Check it and try again.')

    if old_key:
        _discard_result_file(old_key, experiment_request.pk, 'replaced by a new upload')

    logger.info('BER request %s result file replaced by user %s', experiment_request.pk, request.user.pk)
    async_task('digitaltwins.ber.tasks.warm_ber_results_cache', experiment_request.pk)
    async_task(
        'digitaltwins.ber.tasks.notify_ber_results_updated',
        experiment_request.pk, request.build_absolute_uri('/'),
    )
    return _done(request, _list_url(status, page, experiment_request.pk))


@login_required
@manage_permission_required
def ber_management_upload_progress(request):
    """Polled by the panel while the server copies an uploaded result file to MinIO."""
    upload_id = request.GET.get('id', '')
    if not UPLOAD_ID_RE.match(upload_id):
        return JsonResponse({'error': 'Invalid upload id.'}, status=400)
    progress = read_progress(request.user.pk, upload_id)
    return JsonResponse(progress or {'sent': 0, 'total': 0})


@login_required
@manage_permission_required
@require_POST
def ber_management_archive(request, request_id):
    """Hide a decided request from the management list. The requester still sees it."""
    experiment_request = get_object_or_404(BerExperimentRequest.objects.select_related('user'), pk=request_id)
    status, page = _list_filters(request.POST)
    now = datetime.now(timezone.utc)

    archived = BerExperimentRequest.objects.filter(
        pk=experiment_request.pk, archived_at__isnull=True, status__in=BerExperimentRequest.FINISHED_STATUSES,
    ).update(archived_at=now, archived_by=request.user, updated_at=now)

    if not archived:
        experiment_request.refresh_from_db()
        if experiment_request.archived_at:
            message = 'This request is already archived.'
        else:
            message = 'Pending requests cannot be archived. Reject it first so the requester is informed.'
        return _render_management(request, request.POST, selected=experiment_request, error=message)

    logger.info('BER request %s archived by user %s', experiment_request.pk, request.user.pk)
    return redirect(_list_url(status, page))


@login_required
@manage_permission_required
@require_POST
def ber_management_restore(request, request_id):
    """Bring an archived request back into the management list."""
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id)
    status, page = _list_filters(request.POST)
    now = datetime.now(timezone.utc)

    BerExperimentRequest.objects.filter(pk=experiment_request.pk, archived_at__isnull=False).update(
        archived_at=None, archived_by=None, updated_at=now,
    )
    logger.info('BER request %s restored from archive by user %s', experiment_request.pk, request.user.pk)
    return redirect(_list_url(status, page))


@login_required
@manage_permission_required
def ber_management_experiment_download(request, request_id):
    """Download the experiment JSON the requester submitted."""
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id)
    response = HttpResponse(
        json.dumps(experiment_request.experiment_json, indent=2), content_type='application/json',
    )
    response['Content-Disposition'] = f'attachment; filename="experiment_{experiment_request.pk}.json"'
    return response


@login_required
@manage_permission_required
def ber_management_download(request, request_id):
    """Stream any request's uploaded result file (BER staff)."""
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id)
    return result_file_response(experiment_request)
