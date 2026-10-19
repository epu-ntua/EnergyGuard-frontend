"""Run history of the twins that answer straight away (see digitaltwins.runs.services)."""

import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core.services.object_storage import MinioUploadError

from ..catalog import DT_BY_SLUG
from ..common import dt_render, iter_body_chunks
from ..models import DtRun
from .services import open_run_result

logger = logging.getLogger(__name__)

_RUNS_PAGE_SIZE = 20


def runs_config(twin_slug):
    """The twin's catalog entry and its `runs` settings, or 404 if it keeps no runs."""
    digital_twin = DT_BY_SLUG.get(twin_slug)
    if digital_twin is None or 'runs' not in digital_twin:
        raise Http404
    return digital_twin, digital_twin['runs']


def get_user_run(request, run_id, **filters):
    return get_object_or_404(DtRun, pk=run_id, user=request.user, **filters)


def inputs_label(run):
    """A one-line summary of what the run was asked, for the list."""
    inputs = run.inputs or {}
    if run.twin_slug == 'engreen-antrodoco':
        if inputs.get('mode') == 'existing':
            label = f"Station {inputs.get('station', '')}"
        else:
            label = f"New plant · {inputs.get('n_panels')} × {inputs.get('wp_panel')} Wp"
        if inputs.get('days'):
            label += f" · {inputs['days']} days"
        return label
    if run.twin_slug == 'ciemat-microgrid':
        def forecast_label(cfg):
            return f"{str(cfg.get('generation_type', '')).title()} · {cfg.get('lat')}, {cfg.get('lon')}"
        if run.operation == 'compare-forecasts':
            return f"{forecast_label(inputs.get('a', {}))} vs {forecast_label(inputs.get('b', {}))}"
        if run.operation == 'forecast':
            return forecast_label(inputs)
        if run.operation == 'calculate':
            return f"{inputs.get('resolution')} model · device {inputs.get('device_id')}"
        return f"device {inputs.get('device_id')}"
    return ''


@login_required
def dt_runs(request, slug):
    digital_twin, config = runs_config(slug)
    runs = DtRun.objects.filter(user=request.user, twin_slug=slug).order_by('-created_at')
    page_obj = Paginator(runs, _RUNS_PAGE_SIZE).get_page(request.GET.get('page'))
    for run in page_obj:
        run.operation_label = config['operations'].get(run.operation, run.operation)
        run.inputs_label = inputs_label(run)
    return dt_render(request, 'digitaltwins/runs/list.html', digital_twin=digital_twin, runs=config, page_obj=page_obj)


@login_required
def dt_run_result_data(request, run_id):
    """Stream the run's stored result. It is kept gzipped and sent as is, with
    Content-Encoding: gzip, so the browser does the decompressing."""
    run = get_user_run(request, run_id)
    if not run.has_result:
        return JsonResponse({'error': 'This run has no stored result.'}, status=404)
    try:
        body, content_length = open_run_result(run)
    except MinioUploadError:
        logger.exception('Could not read the result of DT run %s', run.pk)
        return JsonResponse({'error': 'The result could not be retrieved.'}, status=502)

    response = StreamingHttpResponse(iter_body_chunks(body), content_type='application/json')
    response['Content-Encoding'] = 'gzip'
    if content_length is not None:
        response['Content-Length'] = str(content_length)
    if request.GET.get('download'):
        response['Content-Disposition'] = f'attachment; filename="{run.twin_slug}-run-{run.pk}.json"'
    return response


@login_required
@require_POST
def dt_run_delete(request, run_id):
    """Delete one of the user's runs; its stored result and JupyterHub copies
    follow it (digitaltwins.signals)."""
    run = get_user_run(request, run_id)
    run.delete()
    return redirect('dt-runs', slug=run.twin_slug)
