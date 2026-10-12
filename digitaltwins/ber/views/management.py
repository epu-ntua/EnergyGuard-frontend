"""BER experiment management (staff-only).

Gated by the 'digitaltwins.manage_ber_requests' permission - grant it via a
Group (e.g. "BER Team") assigned to the BER staff's own EnergyGuard accounts.
"""

import json

from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from digitaltwins.common import dt_render, format_duration
from digitaltwins.models import BerExperimentRequest

from ..forms import CompleteRequestForm, RejectRequestForm, ReplaceResultForm, first_error
from ..services import requests as ber_requests
from ..services.requests import TransitionError
from ..upload_progress import UPLOAD_ID_RE, progress_callback_for, read_progress
from .shared import PAGE_SIZE, result_file_response, result_filename

_ARCHIVED_TAB = 'archived'

manage_permission_required = permission_required('digitaltwins.manage_ber_requests', raise_exception=True)


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
    return dt_render(request, 'digitaltwins/ber/management.html', active_navbar_page='ber_management', **context)


def _wants_json(request):
    """The panel's upload forms are sent by XHR (for the progress bar); they get
    JSON back, while the plain form submit (no JS) keeps the normal page flow."""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _done(request, next_url):
    if _wants_json(request):
        return JsonResponse({'redirect': next_url})
    return redirect(next_url)


def _error(request, experiment_request, message):
    """A failed panel action: JSON for the XHR upload forms, else the page with the error shown."""
    if _wants_json(request):
        return JsonResponse({'error': message}, status=400)
    return _render_management(request, request.POST, selected=experiment_request, error=message)


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
        request, 'digitaltwins/ber/partials/management-panel.html',
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
    action = request.POST.get('action')
    if action not in ('complete', 'reject'):
        return JsonResponse({'error': 'Invalid action.'}, status=400)

    try:
        # Before validating the form: no point scanning an upload for a request
        # that can't be decided any more.
        ber_requests.ensure_pending(experiment_request)

        if action == 'complete':
            form = CompleteRequestForm(request.POST, request.FILES, experiment_request=experiment_request)
        else:
            form = RejectRequestForm(request.POST)
        if not form.is_valid():
            return _error(request, experiment_request, first_error(form))

        if action == 'complete':
            ber_requests.complete_request(
                experiment_request, **form.cleaned_data,
                progress_callback=progress_callback_for(request, form.cleaned_data['result_file']),
            )
        else:
            ber_requests.reject_request(experiment_request, reason=form.cleaned_data['rejection_reason'])
    except TransitionError as exc:
        return _error(request, experiment_request, str(exc))

    return _done(request, _list_url(status, page, experiment_request.pk))


@login_required
@manage_permission_required
@require_POST
def ber_management_replace_result(request, request_id):
    """Swap a completed request's result file (e.g. the wrong file was uploaded)."""
    experiment_request = get_object_or_404(BerExperimentRequest.objects.select_related('user', 'archived_by'), pk=request_id)
    status, page = _list_filters(request.POST)

    if experiment_request.status != BerExperimentRequest.Status.COMPLETED:
        return _error(request, experiment_request, 'Only completed requests have a result file to replace.')

    form = ReplaceResultForm(request.POST, request.FILES)
    if not form.is_valid():
        return _error(request, experiment_request, first_error(form))

    result_file = form.cleaned_data['result_file']
    try:
        ber_requests.replace_result(
            experiment_request, actor=request.user, result_file=result_file,
            progress_callback=progress_callback_for(request, result_file),
        )
    except TransitionError as exc:
        return _error(request, experiment_request, str(exc))

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

    try:
        ber_requests.archive_request(experiment_request, actor=request.user)
    except TransitionError as exc:
        return _render_management(request, request.POST, selected=experiment_request, error=str(exc))
    return redirect(_list_url(status, page))


@login_required
@manage_permission_required
@require_POST
def ber_management_restore(request, request_id):
    """Bring an archived request back into the management list."""
    experiment_request = get_object_or_404(BerExperimentRequest, pk=request_id)
    status, page = _list_filters(request.POST)

    ber_requests.restore_request(experiment_request, actor=request.user)
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
