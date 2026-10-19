import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from digitaltwins.common import check_rate_limit, dt_render
from digitaltwins.runs.services import attach_run_id, record_run
from digitaltwins.runs.views import render_run_page

from . import client

TWIN_SLUG = 'engreen-antrodoco'

_VALID_PROFILES = {'away_during_day', 'mixed_use', 'often_home'}
_MAX_FORECAST_DAYS = 16
_MAX_PANELS = 50


@login_required
def engreen_antrodoco_dt(request):
    return dt_render(request, 'digitaltwins/engreen-antrodoco-dt.html')


@login_required
def engreen_antrodoco_run(request, run_id):
    """One of the user's earlier runs, drawn from its stored result."""
    return render_run_page(request, run_id, twin_slug=TWIN_SLUG, template='digitaltwins/engreen/run.html')


@login_required
def engreen_stations_api(request):
    stations = client.fetch_stations()
    if stations is None:
        return JsonResponse({'error': 'Could not load stations.'}, status=503)
    return JsonResponse(stations)


@login_required
@require_POST
def engreen_pv_simulate(request):
    if not check_rate_limit(request.user.pk, 'engreen'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another simulation.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    mode = body.get('mode')
    forecast_type = body.get('forecast_type')

    if forecast_type not in client.FORECAST_TYPES:
        return JsonResponse({'error': 'Invalid forecast type.'}, status=400)

    payload = {}

    if mode == 'existing':
        station = str(body.get('station', '')).strip()
        if not station:
            return JsonResponse({'error': 'A station must be selected.'}, status=400)
        payload['station'] = station

    elif mode == 'new':
        try:
            n_panels = int(body['n_panels'])
            wp_panel = int(body['wp_panel'])
            tilt     = int(body['tilt'])
            azimuth  = int(body['azimuth'])
        except (KeyError, TypeError, ValueError):
            return JsonResponse({'error': 'Invalid or missing plant parameters.'}, status=400)

        if not (1 <= n_panels <= _MAX_PANELS):
            return JsonResponse({'error': f'n_panels must be between 1 and {_MAX_PANELS}.'}, status=400)

        profile = str(body.get('profile', ''))
        if profile not in _VALID_PROFILES:
            return JsonResponse({'error': 'Invalid consumption profile.'}, status=400)

        payload.update({'n_panels': n_panels, 'wp_panel': wp_panel,
                        'tilt': tilt, 'azimuth': azimuth, 'profile': profile})
    else:
        return JsonResponse({'error': 'Invalid mode.'}, status=400)

    if forecast_type == 'short-term':
        try:
            days = max(1, min(_MAX_FORECAST_DAYS, int(body.get('days', 10))))
        except (TypeError, ValueError):
            days = 10
        payload['days'] = days

    data, error, status = client.simulate(forecast_type, payload)
    run = record_run(
        user=request.user, twin_slug=TWIN_SLUG, operation=forecast_type,
        inputs={'mode': mode, **payload}, result=data, error=error or '',
    )
    if error:
        return JsonResponse({'error': error}, status=status)
    return attach_run_id(JsonResponse(data), run)
