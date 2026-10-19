"""Run history of the twins that answer straight away (see digitaltwins.runs.services)."""

import gzip
import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_POST

from core.services.object_storage import MinioUploadError

from ..catalog import DT_BY_SLUG
from ..common import RESULT_STREAM_CHUNK, RUNS_PAGE_SIZE, dt_render, iter_body_chunks
from ..models import DtRun
from .descriptions import describe_inputs
from .services import open_run_result

logger = logging.getLogger(__name__)



def runs_config(twin_slug):
    """The twin's catalog entry and its `runs` settings, or 404 if it keeps no runs."""
    digital_twin = DT_BY_SLUG.get(twin_slug)
    if digital_twin is None or 'runs' not in digital_twin:
        raise Http404
    return digital_twin, digital_twin['runs']


def get_user_run(request, run_id, **filters):
    return get_object_or_404(DtRun, pk=run_id, user=request.user, **filters)


def render_run_page(request, run_id, *, twin_slug, template):
    """The page of one of the user's completed runs of `twin_slug`: `template`
    extends digitaltwins/runs/run-base.html with the twin's results partial."""
    digital_twin, config = runs_config(twin_slug)
    run = get_user_run(request, run_id, twin_slug=twin_slug, status=DtRun.Status.COMPLETED)
    return dt_render(
        request, template, run=run, digital_twin=digital_twin, runs=config,
        operation_label=config['operations'].get(run.operation, run.operation),
    )


@login_required
def dt_runs(request, slug):
    digital_twin, config = runs_config(slug)
    runs = DtRun.objects.filter(user=request.user, twin_slug=slug).order_by('-created_at')
    page_obj = Paginator(runs, RUNS_PAGE_SIZE).get_page(request.GET.get('page'))
    for run in page_obj:
        run.operation_label = config['operations'].get(run.operation, run.operation)
        run.inputs_label = describe_inputs(run)
    return dt_render(request, 'digitaltwins/runs/list.html', digital_twin=digital_twin, runs=config, page_obj=page_obj)


def _accepts_gzip(request):
    return 'gzip' in request.META.get('HTTP_ACCEPT_ENCODING', '').lower()


def _decompressed_chunks(body):
    """The stored gzip body, decompressed as it streams; closes the body when done."""
    try:
        with gzip.GzipFile(fileobj=body) as decompressed:
            while chunk := decompressed.read(RESULT_STREAM_CHUNK):
                yield chunk
    finally:
        body.close()


@login_required
def dt_run_result_data(request, run_id):
    """Stream the run's stored result.

    It is kept gzipped. A client that accepts gzip - every browser - gets it as
    is, with Content-Encoding: gzip, and decompresses it itself; any other (a
    script, curl without --compressed) gets it decompressed on the way out.
    """
    run = get_user_run(request, run_id)
    if not run.has_result:
        return JsonResponse({'error': 'This run has no stored result.'}, status=404)
    try:
        body, content_length = open_run_result(run)
    except MinioUploadError:
        logger.exception('Could not read the result of DT run %s', run.pk)
        return JsonResponse({'error': 'The result could not be retrieved.'}, status=502)

    if _accepts_gzip(request):
        response = StreamingHttpResponse(iter_body_chunks(body), content_type='application/json')
        response['Content-Encoding'] = 'gzip'
        if content_length is not None:
            response['Content-Length'] = str(content_length)
    else:
        response = StreamingHttpResponse(_decompressed_chunks(body), content_type='application/json')
    # The body depends on Accept-Encoding; caches must not hand one form to the other.
    patch_vary_headers(response, ['Accept-Encoding'])
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
