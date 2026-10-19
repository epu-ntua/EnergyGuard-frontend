import json
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from digitaltwins.catalog import DT_BY_SLUG
from digitaltwins.common import check_rate_limit, dt_render
from digitaltwins.models import DtRun
from digitaltwins.runs.services import attach_run_id, record_run
from digitaltwins.runs.views import get_user_run

from . import client

TWIN_SLUG = 'ciemat-microgrid'

_NOT_CONFIGURED = 'The CIEMAT forecasting service is not configured yet.'


@login_required
def ciemat_forecasting_dt(request):
    return dt_render(request, 'digitaltwins/ciemat-forecasting-dt.html')


@login_required
def ciemat_microgrid_run(request, run_id):
    """One of the user's earlier runs, drawn from its stored result."""
    run = get_user_run(request, run_id, twin_slug=TWIN_SLUG, status=DtRun.Status.COMPLETED)
    operation_label = DT_BY_SLUG[TWIN_SLUG]['runs']['operations'].get(run.operation, run.operation)
    return dt_render(request, 'digitaltwins/ciemat/run.html', run=run, operation_label=operation_label)


def _forecast_inputs(body):
    """({generation_type, lat, lon}, None) for one forecast model, or (None, error)."""
    if not isinstance(body, dict):
        return None, 'Invalid forecast configuration.'

    generation_type = body.get('generation_type')
    if generation_type not in ('wind', 'solar'):
        return None, 'Invalid generation type.'

    try:
        lat = float(body.get('lat'))
        lon = float(body.get('lon'))
    except (TypeError, ValueError):
        return None, 'Invalid or missing coordinates.'

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None, 'Coordinates out of range.'

    return {'generation_type': generation_type, 'lat': lat, 'lon': lon}, None


@login_required
@require_POST
def ciemat_forecast(request):
    if not check_rate_limit(request.user.pk, 'ciemat'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another forecast.'}, status=429)

    if not client.is_configured():
        return JsonResponse({'error': _NOT_CONFIGURED}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    inputs, error = _forecast_inputs(body)
    if error:
        return JsonResponse({'error': error}, status=400)

    points, error, status = client.forecast(inputs['generation_type'], inputs['lat'], inputs['lon'])
    result = {'points': points}
    run = record_run(
        user=request.user, twin_slug=TWIN_SLUG, operation='forecast', inputs=inputs, result=result, error=error or '',
    )
    if error:
        return JsonResponse({'error': error}, status=status)
    return attach_run_id(JsonResponse(result), run)


@login_required
@require_POST
def ciemat_compare_forecasts(request):
    """Forecast two configurations side by side ("Compare with a second model").

    One request and one recorded run, so the run history shows the comparison and
    its page can draw it; the browser used to make two separate forecast calls.
    """
    if not check_rate_limit(request.user.pk, 'ciemat'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another forecast.'}, status=429)

    if not client.is_configured():
        return JsonResponse({'error': _NOT_CONFIGURED}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    inputs = {}
    for model in ('a', 'b'):
        inputs[model], error = _forecast_inputs(body.get(model))
        if error:
            return JsonResponse({'error': f'Model {model.upper()}: {error}'}, status=400)

    # Independent calls against the same service, so run them concurrently.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            model: executor.submit(client.forecast, cfg['generation_type'], cfg['lat'], cfg['lon'])
            for model, cfg in inputs.items()
        }
        outcomes = {model: future.result() for model, future in futures.items()}

    result = {}
    for model in ('a', 'b'):
        points, error, status = outcomes[model]
        if error:
            message = f'Model {model.upper()}: {error}'
            record_run(user=request.user, twin_slug=TWIN_SLUG, operation='compare-forecasts', inputs=inputs, error=message)
            return JsonResponse({'error': message}, status=status)
        result[model] = {'points': points}

    run = record_run(
        user=request.user, twin_slug=TWIN_SLUG, operation='compare-forecasts', inputs=inputs, result=result,
    )
    return attach_run_id(JsonResponse(result), run)


@login_required
@require_POST
def ciemat_calculate(request):
    if not check_rate_limit(request.user.pk, 'ciemat_calc'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another calculation.'}, status=429)

    if not client.is_configured():
        return JsonResponse({'error': _NOT_CONFIGURED}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    resolution = body.get('resolution')
    if resolution not in client.CALCULATE_ROUTES:
        return JsonResponse({'error': 'Invalid resolution.'}, status=400)

    payload, error = client.build_calculate_payload(resolution, body)
    if error:
        return JsonResponse({'error': error}, status=400)

    power, error, status = client.calculate(resolution, payload)
    result = {'power_w': power, 'timestamp': payload['timestamp']}
    run = record_run(
        user=request.user, twin_slug=TWIN_SLUG, operation='calculate',
        inputs={'resolution': resolution, **payload}, result=result, error=error or '',
    )
    if error:
        return JsonResponse({'error': error}, status=status)

    return attach_run_id(JsonResponse(result), run)


@login_required
@require_POST
def ciemat_compare(request):
    if not check_rate_limit(request.user.pk, 'ciemat_compare'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another comparison.'}, status=429)

    if not client.is_configured():
        return JsonResponse({'error': _NOT_CONFIGURED}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    resolutions = ('1min', '5min', '1s')
    payloads = {}
    for resolution in resolutions:
        payload, error = client.build_calculate_payload(resolution, body)
        if error:
            return JsonResponse({'error': error}, status=400)
        payloads[resolution] = payload

    # The three resolutions are independent calls against the same service,
    # so run them concurrently instead of paying up to 3x the calculate timeout.
    with ThreadPoolExecutor(max_workers=len(resolutions)) as executor:
        futures = {
            resolution: executor.submit(client.calculate, resolution, payloads[resolution])
            for resolution in resolutions
        }
        outcomes = {resolution: future.result() for resolution, future in futures.items()}

    # The 1s payload carries every input the other models take, plus the lags.
    inputs = {key: value for key, value in payloads['1s'].items() if key != 'timestamp'}

    results = {}
    for resolution in resolutions:
        power, error, status = outcomes[resolution]
        if error:
            message = f'{resolution} model: {error}'
            record_run(user=request.user, twin_slug=TWIN_SLUG, operation='compare', inputs=inputs, error=message)
            return JsonResponse({'error': message}, status=status)
        results[resolution] = power

    run = record_run(
        user=request.user, twin_slug=TWIN_SLUG, operation='compare', inputs=inputs, result={'results': results},
    )
    return attach_run_id(JsonResponse({'results': results}), run)
