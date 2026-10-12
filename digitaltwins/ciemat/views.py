import json
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from digitaltwins.common import check_rate_limit, dt_render

from . import client

_NOT_CONFIGURED = 'The CIEMAT forecasting service is not configured yet.'


@login_required
def ciemat_forecasting_dt(request):
    return dt_render(request, 'digitaltwins/ciemat-forecasting-dt.html')


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

    generation_type = body.get('generation_type')
    if generation_type not in ('wind', 'solar'):
        return JsonResponse({'error': 'Invalid generation type.'}, status=400)

    try:
        lat = float(body.get('lat'))
        lon = float(body.get('lon'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid or missing coordinates.'}, status=400)

    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JsonResponse({'error': 'Coordinates out of range.'}, status=400)

    points, error, status = client.forecast(generation_type, lat, lon)
    if error:
        return JsonResponse({'error': error}, status=status)
    return JsonResponse({'points': points})


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
    if error:
        return JsonResponse({'error': error}, status=status)

    return JsonResponse({'power_w': power, 'timestamp': payload['timestamp']})


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

    results = {}
    for resolution in resolutions:
        power, error, status = outcomes[resolution]
        if error:
            return JsonResponse({'error': f'{resolution} model: {error}'}, status=status)
        results[resolution] = power

    return JsonResponse({'results': results})
