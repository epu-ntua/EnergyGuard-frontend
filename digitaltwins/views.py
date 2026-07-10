import json
import logging
from functools import lru_cache
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

_HAL_BASE = settings.HAL_BASE_URL
_VALID_PROFILES = {'away_during_day', 'mixed_use', 'often_home'}

# Fallback used when the HAL /stations endpoint is unreachable.
_ENGREEN_STATIONS_FALLBACK = {
    'IT001E61366665':  {'pnom_kw': 2.975, 'tilt': 30, 'azimuth': 0, 'profile': 'often_home',      'ratio_feed_in': 0.26},
    'IT001E61366666':  {'pnom_kw': 2.975, 'tilt': 30, 'azimuth': 0, 'profile': 'mixed_use',       'ratio_feed_in': 0.46},
    'IT001E61366667':  {'pnom_kw': 2.975, 'tilt': 30, 'azimuth': 0, 'profile': 'often_home',      'ratio_feed_in': 0.26},
    'IT001E61493931':  {'pnom_kw': 3.4,   'tilt': 30, 'azimuth': 0, 'profile': 'often_home',      'ratio_feed_in': 0.26},
    'IT001E61493111':  {'pnom_kw': 3.4,   'tilt': 30, 'azimuth': 0, 'profile': 'away_during_day', 'ratio_feed_in': 0.76},
    'IT001E61493112':  {'pnom_kw': 3.4,   'tilt': 30, 'azimuth': 0, 'profile': 'away_during_day', 'ratio_feed_in': 0.76},
    'IT001E61493825':  {'pnom_kw': 5.0,   'tilt': 30, 'azimuth': 0, 'profile': 'mixed_use',       'ratio_feed_in': 0.46},
    'IT001E687790740': {'pnom_kw': 6.0,   'tilt': 30, 'azimuth': 0, 'profile': 'mixed_use',       'ratio_feed_in': 0.46},
    'IT001E61376264':  {'pnom_kw': 4.0,   'tilt': 30, 'azimuth': 0, 'profile': 'mixed_use',       'ratio_feed_in': 0.46},
}


_SIMULATE_RATE_LIMIT = 20   # max requests per user per window
_SIMULATE_RATE_WINDOW = 60  # seconds

_HAL_STATIONS_TIMEOUT = 5   # seconds
_HAL_SIMULATE_TIMEOUT = 30  # seconds
_MAX_FORECAST_DAYS    = 16
_MAX_PANELS           = 50


def _check_simulate_rate_limit(user_id):
    key = f'engreen_simulate_rl_{user_id}'
    count = cache.get(key, 0)
    if count >= _SIMULATE_RATE_LIMIT:
        return False
    cache.set(key, count + 1, timeout=_SIMULATE_RATE_WINDOW)
    return True


def _fetch_engreen_stations():
    try:
        resp = requests.get(f'{_HAL_BASE}/stations', timeout=_HAL_STATIONS_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning('Could not fetch stations from HAL; using fallback registry. Reason: %s', exc)
        return _ENGREEN_STATIONS_FALLBACK

DIGITAL_TWINS = [
    {
        'slug': 'portuguese-grid',
        'name': 'Large-Scale Portuguese Transmission Network',
        'description': "A comprehensive Digital Twin of Portugal's large-scale transmission grid, designed to support power systems with high shares of renewable energy.",
        'image': 'assets/img/digital_twins/RDN.png',
    },
    {
        'slug': 'ceder-microgrid',
        'name': 'CEDER-CIEMAT Microgrid with Distributed Energy Resources',
        'description': 'A real renewable microgrid with solar, wind, storage, and hydrogen integration, supported by a Digital Twin for testing intelligent energy management strategies.',
        'image': 'assets/img/digital_twins/Ceder-Lubia.jpg',
    },
    {
        'slug': 'cea-hydrogen',
        'name': 'Solid Oxide Electrolysis Cell System',
        'description': 'A physics-based Digital Twin of a Solid Oxide Electrolysis Cell (SOEC) system, enabling scenario configuration, simulation execution, and performance analysis.',
        'image': 'assets/img/digital_twins/hydrogenCEA.jpg',
    },
    {
        'slug': 'ber-hydrogen',
        'name': 'PEM Electrolyzer Testing Facility',
        'description': 'Physical PEM Electrolyzer Testing Facility. Experiments are executed manually by the BER laboratory team.',
        'image': 'assets/img/digital_twins/BER.jpg',
    },
    {
        'slug': 'cartif-hydrogen',
        'name': 'CARTIF Hydrogen Node',
        'description': 'Hybrid hydrogen-electric-thermal energy system combining hydrogen production, storage, batteries, and thermal storage for Digital Twin-based simulation and AI optimization.',
        'image': 'assets/img/digital_twins/DT_CARTIF updated.png',
    },
    {
        'slug': 'rea-riga',
        'name': "Riga's Multi-Apartment Residential Buildings",
        'description': "A city-scale Digital Twin of Riga's residential buildings, supporting energy efficiency analysis and renovation planning.",
        'image': 'assets/img/digital_twins/REA.png',
    },
    {
        'slug': 'engreen-antrodoco',
        'name': 'Antrodoco Renewable Energy Community',
        'description': 'A renewable energy community, digitally modelled for community-level energy management and optimization.',
        'image': 'assets/img/digital_twins/antrodoco.png',
    },
]

_DT_BY_SLUG = {dt['slug']: dt for dt in DIGITAL_TWINS}

CEA_VALIDATION_CHECKS = [
    'All required variables present',
    'Correct data types and ranges',
    'Signals have the same length as timeStamp',
]

CEA_SAMPLE_JSON = """{
    "timeStamp": [0, 60, 120, 180, 240],
    "current": [-50, -60, -60, -40, -20],
    "voltageCell": [1.290, 1.292, 1.291, 1.289, 1.288],
    "temperatureHotbox": [750, 752, 751, 750, 748],
    "steamConversion": [0.85, 0.86, 0.87, 0.88, 0.88],
    "fuelElectrode_ratioH2O": [0.85, 0.85, 0.86, 0.86, 0.87],
    "fuelElectrode_flowrate": [120, 120, 118, 115, 110],
    "oxygenElectrode_flowrate": [80, 80, 80, 75, 70],
    "deltaP": [20, 20, 22, 22, 25],
    "coef_degradPerf[1]": 1.00,
    "coef_degradPerf[2]": 0.95,
    "coef_degradPerf[3]": 1.10,
    "coef_degradPerf[4]": 0.90
}"""

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


def _dt_render(request, template, **extra):
    return render(request, template, {'show_sidebar': True, 'active_navbar_page': 'facilities', **extra})


_RIGA_BUILDINGS_PATH = Path(__file__).resolve().parent / 'static' / 'digitaltwins' / 'DT_data.json'


def _iter_coordinates(coords):
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        yield coords
        return
    for item in coords:
        yield from _iter_coordinates(item)


def _feature_bbox(feature):
    geometry = feature.get('geometry') or {}
    lons, lats = [], []
    for lon, lat in _iter_coordinates(geometry.get('coordinates')):
        lons.append(lon)
        lats.append(lat)
    return (min(lons), min(lats), max(lons), max(lats)) if lons else None


@lru_cache(maxsize=1)
def _load_riga_buildings():
    with open(_RIGA_BUILDINGS_PATH, encoding='utf-8') as f:
        data = json.load(f, parse_constant=lambda _: None)
    indexed = []
    for feature in data.get('features', []):
        bbox = _feature_bbox(feature)
        if bbox:
            indexed.append((bbox, feature))
    return indexed


@login_required
def rea_riga_dt(request):
    return _dt_render(request, 'digitaltwins/rea-riga-dt.html')


@login_required
def rea_riga_buildings_api(request):
    try:
        min_lon = float(request.GET['min_lon'])
        min_lat = float(request.GET['min_lat'])
        max_lon = float(request.GET['max_lon'])
        max_lat = float(request.GET['max_lat'])
    except (KeyError, ValueError):
        return JsonResponse({'error': 'Invalid or missing bbox parameters.'}, status=400)

    features = [
        feature for (f_min_lon, f_min_lat, f_max_lon, f_max_lat), feature in _load_riga_buildings()
        if f_min_lon <= max_lon and f_max_lon >= min_lon and f_min_lat <= max_lat and f_max_lat >= min_lat
    ]
    return JsonResponse({'type': 'FeatureCollection', 'features': features})


@login_required
def digitaltwins_list(request):
    return _dt_render(request, 'digitaltwins/digitaltwins-list.html', digital_twins=DIGITAL_TWINS)


@login_required
def cea_node_workspace(request):
    return _dt_render(request, 'digitaltwins/cea-hydrogen-dt.html',
                      validation_checks=CEA_VALIDATION_CHECKS, sample_json=CEA_SAMPLE_JSON)


@login_required
def cea_ai_scenario_generation(request):
    return _dt_render(request, 'digitaltwins/cea-ai-scenario-generation.html')


@login_required
def cea_dt_simulation(request):
    return _dt_render(request, 'digitaltwins/cea-dt-simulation.html',
                      validation_checks=CEA_VALIDATION_CHECKS, sample_json=CEA_SAMPLE_JSON)


@login_required
def ber_hydrogen_dt(request):
    return _dt_render(request, 'digitaltwins/ber-hydrogen-dt.html',
                      validation_checks=BER_VALIDATION_CHECKS, sample_json=BER_SAMPLE_JSON)


@login_required
def cartif_hydrogen_dt(request):
    return _dt_render(request, 'digitaltwins/cartif-hydrogen-dt.html')


@login_required
def engreen_antrodoco_dt(request):
    return _dt_render(request, 'digitaltwins/engreen-antrodoco-dt.html')


@login_required
def engreen_stations_api(request):
    return JsonResponse(_fetch_engreen_stations())


@login_required
@require_POST
def engreen_pv_simulate(request):
    if not _check_simulate_rate_limit(request.user.pk):
        return JsonResponse({'error': 'Too many requests. Please wait before running another simulation.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    mode = body.get('mode')
    forecast_type = body.get('forecast_type')

    if forecast_type not in ('short-term', 'historical', 'optimistic'):
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
        hal_url = f'{_HAL_BASE}/simulate'
    elif forecast_type == 'historical':
        hal_url = f'{_HAL_BASE}/simulate/annual/historical'
    else:
        hal_url = f'{_HAL_BASE}/simulate/annual/optimistic'

    try:
        resp = requests.post(hal_url, json=payload, timeout=_HAL_SIMULATE_TIMEOUT)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            logger.error('HAL returned non-JSON body (status %s): %s', resp.status_code, resp.text[:200])
            return JsonResponse({'error': 'The forecast service returned an unexpected response.'}, status=502)
        return JsonResponse(data)
    except requests.Timeout:
        return JsonResponse({'error': 'The forecast service timed out. Please try again.'}, status=504)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        if 400 <= code < 500:
            return JsonResponse(
                {'error': 'The forecast service rejected the configuration. Check your inputs.'},
                status=422,
            )
        return JsonResponse({'error': 'The forecast service is temporarily unavailable.'}, status=502)
    except requests.RequestException:
        logger.exception('HAL request failed: url=%s', hal_url)
        return JsonResponse({'error': 'Could not reach the forecast service.'}, status=502)


@login_required
def digitaltwins_detail(request, slug):
    digital_twin = _DT_BY_SLUG.get(slug)
    if digital_twin is None:
        raise Http404
    return _dt_render(request, f'digitaltwins/{slug}.html', digital_twin=digital_twin)
