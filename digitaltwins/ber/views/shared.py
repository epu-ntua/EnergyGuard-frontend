"""View helpers used by both the requester and the BER staff pages."""

import logging

from django.http import JsonResponse, StreamingHttpResponse

from core.services.object_storage import MinioUploadError
from digitaltwins.common import iter_body_chunks

from ..services.results import ber_experiment_id
from ..services.storage import open_result_file

logger = logging.getLogger(__name__)

PAGE_SIZE = 20


def result_file_response(experiment_request):
    """Stream a request's uploaded result file, named after its experiment ID."""
    if not experiment_request.result_key:
        return JsonResponse({'error': 'This request has no result file.'}, status=404)

    try:
        body, content_length = open_result_file(experiment_request.result_key)
    except MinioUploadError:
        logger.exception('Could not read BER result file for request %s', experiment_request.pk)
        return JsonResponse({'error': 'The result file could not be retrieved.'}, status=502)

    response = StreamingHttpResponse(iter_body_chunks(body), content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{result_filename(experiment_request)}"'
    if content_length is not None:
        response['Content-Length'] = content_length
    return response


def result_filename(experiment_request):
    """Download name of the result file: the experiment ID plus the uploaded extension."""
    extension = experiment_request.result_key.rsplit('.', 1)[-1]
    return f'{ber_experiment_id(experiment_request)}.{extension}'
