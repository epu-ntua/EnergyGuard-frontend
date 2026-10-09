import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from core.services.object_storage import MinioUploadError
from datasets.services import provision_user_datasets

from .common import RESULT_STREAM_CHUNK, check_rate_limit, dt_render, format_duration
from .models import RdnSimulationJob
from .services import (
    save_simulation_result,
    RdnApiError,
    open_result_stream,
    upload_rdn_input,
)

logger = logging.getLogger(__name__)

_HAL_BASE = settings.HAL_BASE_URL
_VALID_PROFILES = {'away_during_day', 'mixed_use', 'often_home'}

_HAL_STATIONS_TIMEOUT = 5   # seconds
_HAL_SIMULATE_TIMEOUT = 30  # seconds
_MAX_FORECAST_DAYS    = 16
_MAX_PANELS           = 50

_CIEMAT_API_BASE = settings.CIEMAT_API_BASE_URL.rstrip('/')
_CIEMAT_API_KEY = settings.CIEMAT_API_KEY
_CIEMAT_FORECAST_TIMEOUT = 30   # seconds
_CIEMAT_CALCULATE_TIMEOUT = 15  # seconds

_CIEMAT_CALCULATE_ROUTES = {
    '1s':    'calculate/1s',
    '1min':  'calculate/1min',
    '5min':  'calculate/5min',
    'solar': 'calculate/solar',
}


def _fetch_engreen_stations():
    try:
        resp = requests.get(f'{_HAL_BASE}/stations', timeout=_HAL_STATIONS_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning('Could not fetch stations from HAL. Reason: %s', exc)
        return None

DIGITAL_TWINS = [
    {
        'slug': 'rdn-grid',
        'name': 'Large-Scale Portuguese Transmission Network',
        'description': "A comprehensive Digital Twin of Portugal's large-scale transmission grid, designed to support power systems with high shares of renewable energy.",
        'image': 'assets/img/digital_twins/thumbs/RDN.webp',
    },
    {
        'slug': 'ciemat-microgrid',
        'name': 'CIEMAT Microgrid with Distributed Energy Resources',
        'description': 'A real renewable microgrid with solar, wind, storage, and hydrogen integration, supported by a Digital Twin for testing intelligent energy management strategies.',
        'image': 'assets/img/digital_twins/thumbs/Ceder-Lubia.webp',
    },
    {
        'slug': 'cea-hydrogen',
        'name': 'Solid Oxide Electrolysis Cell System',
        'description': 'A physics-based Digital Twin of a Solid Oxide Electrolysis Cell (SOEC) system, enabling scenario configuration, simulation execution, and performance analysis.',
        'image': 'assets/img/digital_twins/thumbs/hydrogenCEA.webp',
    },
    {
        'slug': 'ber-hydrogen',
        'name': 'PEM Electrolyzer Testing Facility',
        'description': 'Physical PEM Electrolyzer Testing Facility. Experiments are executed manually by the BER laboratory team.',
        'image': 'assets/img/digital_twins/thumbs/BER.webp',
    },
    {
        'slug': 'cartif-hydrogen',
        'name': 'CARTIF Hybrid Hydrogen-Electrical-Thermal Energy System',
        'description': 'Hybrid hydrogen-electric-thermal energy system combining hydrogen production, storage, batteries, and thermal storage for Digital Twin-based simulation and AI optimization.',
        'image': 'assets/img/digital_twins/thumbs/DT_CARTIF updated.webp',
    },
    {
        'slug': 'rea-riga',
        'name': "Riga's Multi-Apartment Residential Buildings",
        'description': "A city-scale Digital Twin of Riga's residential buildings, supporting energy efficiency analysis and renovation planning.",
        'image': 'assets/img/digital_twins/thumbs/REA.webp',
    },
    {
        'slug': 'engreen-antrodoco',
        'name': 'Antrodoco Renewable Energy Community',
        'description': 'A renewable energy community, digitally modelled for community-level energy management and optimization.',
        'image': 'assets/img/digital_twins/thumbs/antrodoco.webp',
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

# ── RDN Grid DT ──────────────────────────────────────────────────────────────
# Calls the real R&D Nester Digital Twin API (digitaltwins/services/rdn_client.py).
# RDN jobs run for many minutes to over an hour, so simulation is asynchronous:
# rdn_grid_simulate uploads the input and returns immediately, digitaltwins/tasks.py
# polls RDN in the background (via django_q), and the frontend polls rdn_grid_job_status.

RDN_USE_CASES = {
    'MarketResultsTechnicalValidation': 'Validation of Market Results',
    'VoltageControl': 'Voltage control',
    'GovernorLoadFrequencyControl': 'Governor and load frequency control',
}
RDN_LOCKED_USE_CASES = [
    {'label': 'Short-circuit analysis'},
    {'label': 'Stator transient'},
    {'label': 'Subsynchronous resonance'},
    {'label': 'Inverter-based control'},
]
RDN_GRID_SECTIONS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'All']
RDN_ASSET_TYPES = ['PV', 'Wind', 'SmallHydro', 'Biomass', 'LargeHydro', 'Gas', 'Load']

_RDN_MAX_ASSETS = 25          # well under the schema's 1000, kept usable in a hand-built form
_RDN_MAX_SETPOINTS = 100      # == schema max
_RDN_MAX_OUTPUT_SAMPLES = 75_500_000  # matches the worst case allowed by _RDN_MAX_ASSETS/_RDN_MAX_SETPOINTS/_RDN_MAX_SPAN_MS

_RDN_STEP_MS = 2
_RDN_MAX_SPAN_MS = 10_000            # output covers at most 10s per setpoint
_RDN_DEFAULT_LAST_RESOLUTION_MS = 900_000  # 15 min, used only when there's a single setpoint

_RDN_SIMULATE_RATE_LIMIT = 5  # lower than the default: real RDN jobs are far heavier than a typical request
_RDN_SIMULATE_RATE_WINDOW = 60


def _iso_to_epoch_ms(ts):
    return int(datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp() * 1000)


def _validate_rdn_grid_input(body):
    if not isinstance(body, dict):
        return None, 'Request body must be a JSON object.'

    use_case = body.get('useCase')
    follows_request_id = body.get('followsRequestId')
    input_data = body.get('inputData')

    if use_case not in RDN_USE_CASES:
        return None, 'useCase must be one of the supported automatic-interaction use cases.'

    if follows_request_id is not None and (not isinstance(follows_request_id, int) or isinstance(follows_request_id, bool)):
        return None, 'followsRequestId must be an integer.'

    if not isinstance(input_data, dict):
        return None, 'inputData is required.'

    grid_section = input_data.get('gridSection')
    if grid_section not in RDN_GRID_SECTIONS:
        return None, 'inputData.gridSection must be one of A-G or All.'

    asset = input_data.get('asset')
    if not isinstance(asset, dict) or not (1 <= len(asset) <= _RDN_MAX_ASSETS):
        return None, f'inputData.asset must contain between 1 and {_RDN_MAX_ASSETS} assets.'

    cleaned_assets = {}
    shared_timestamps_ms = None
    for asset_id, asset_body in asset.items():
        if not re.fullmatch(r'asset_\d{3}', asset_id):
            return None, f'Invalid asset key "{asset_id}" (expected asset_NNN).'
        if not isinstance(asset_body, dict):
            return None, f'Asset "{asset_id}" must be an object.'

        asset_type = asset_body.get('assetType')
        if asset_type not in RDN_ASSET_TYPES:
            return None, f'Asset "{asset_id}" has an invalid assetType.'

        series = asset_body.get('assetTimeSeries')
        if not isinstance(series, list) or not (1 <= len(series) <= _RDN_MAX_SETPOINTS):
            return None, f'Asset "{asset_id}" must have between 1 and {_RDN_MAX_SETPOINTS} time-series points.'

        cleaned_points = []
        timestamps_ms = []
        for point in series:
            if not isinstance(point, dict) or not set(point).issubset({'timestamp_UTC', 'MW', 'MVAr'}):
                return None, f'Asset "{asset_id}" has a time-series point with unexpected fields.'

            ts = point.get('timestamp_UTC')
            try:
                ts_ms = _iso_to_epoch_ms(ts)
            except (ValueError, TypeError):
                return None, f'Asset "{asset_id}" has an invalid timestamp_UTC.'

            mw = point.get('MW')
            mvar = point.get('MVAr')
            if mw is not None and not isinstance(mw, (int, float)):
                return None, f'Asset "{asset_id}" has a non-numeric MW value.'
            if mvar is not None and not isinstance(mvar, (int, float)):
                return None, f'Asset "{asset_id}" has a non-numeric MVAr value.'
            if not ((mw not in (None, 0)) or (mvar not in (None, 0))):
                return None, f'Asset "{asset_id}" has a time-series point with no non-zero MW or MVAr.'

            cleaned_points.append({'timestamp_UTC': ts, 'MW': mw, 'MVAr': mvar})
            timestamps_ms.append(ts_ms)

        if len(set(timestamps_ms)) != len(timestamps_ms) or timestamps_ms != sorted(timestamps_ms):
            return None, f'Asset "{asset_id}" timestamps must be strictly increasing.'

        if shared_timestamps_ms is None:
            shared_timestamps_ms = timestamps_ms
        elif timestamps_ms != shared_timestamps_ms:
            return None, 'All assets must share the same setpoint timestamps.'

        cleaned_assets[asset_id] = {'assetType': asset_type, 'assetTimeSeries': cleaned_points}

    resolutions_ms = [_rdn_derive_resolution_ms(shared_timestamps_ms, i) for i in range(len(shared_timestamps_ms))]
    total_points = sum(_rdn_n_points_for_resolution(r) for r in resolutions_ms)
    total_samples = len(cleaned_assets) * 3 * 2 * total_points + total_points
    if total_samples > _RDN_MAX_OUTPUT_SAMPLES:
        return None, (
            f'Request too large: computed {total_samples:,} output samples, exceeding the '
            f'{_RDN_MAX_OUTPUT_SAMPLES:,}-sample limit. Reduce setpoints, assets, or resolution.'
        )

    cleaned = {
        'useCase': use_case,
        'followsRequestId': follows_request_id,
        'inputData': {'gridSection': grid_section, 'asset': cleaned_assets},
    }
    return cleaned, None


def _rdn_derive_resolution_ms(timestamps_ms, index):
    if index < len(timestamps_ms) - 1:
        return timestamps_ms[index + 1] - timestamps_ms[index]
    if len(timestamps_ms) > 1:
        return timestamps_ms[index] - timestamps_ms[index - 1]
    return _RDN_DEFAULT_LAST_RESOLUTION_MS


def _rdn_n_points_for_resolution(resolution_ms):
    span_ms = min(resolution_ms, _RDN_MAX_SPAN_MS)
    return max(1, round(span_ms / _RDN_STEP_MS))


_RIGA_BUILDINGS_PATH = Path(__file__).resolve().parent / 'static' / 'digitaltwins' / 'data' / 'DT_data.json'


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
    return dt_render(request, 'digitaltwins/rea-riga-dt.html')


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
    return dt_render(request, 'digitaltwins/digitaltwins-list.html', digital_twins=DIGITAL_TWINS)


@login_required
def cea_ai_scenario_generation(request):
    return dt_render(request, 'digitaltwins/cea-ai-scenario-generation.html')


@login_required
def cea_dt_simulation(request):
    return dt_render(request, 'digitaltwins/cea-dt-simulation.html', sample_json=CEA_SAMPLE_JSON)


@login_required
def cea_dt_documentation(request):
    return dt_render(request, 'digitaltwins/cea-dt-simulation-documentation.html',
                      validation_checks=CEA_VALIDATION_CHECKS, sample_json=CEA_SAMPLE_JSON)


@login_required
def cartif_hydrogen_dt(request):
    return dt_render(request, 'digitaltwins/cartif-hydrogen-dt.html')


@login_required
def engreen_antrodoco_dt(request):
    return dt_render(request, 'digitaltwins/engreen-antrodoco-dt.html')


@login_required
def engreen_stations_api(request):
    stations = _fetch_engreen_stations()
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
def ciemat_forecasting_dt(request):
    return dt_render(request, 'digitaltwins/ciemat-forecasting-dt.html')


@login_required
@require_POST
def ciemat_forecast(request):
    if not check_rate_limit(request.user.pk, 'ciemat'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another forecast.'}, status=429)

    if not _CIEMAT_API_KEY:
        return JsonResponse({'error': 'The CIEMAT forecasting service is not configured yet.'}, status=503)

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

    forecast_url = f'{_CIEMAT_API_BASE}/api/v1/forecast/{generation_type}'
    headers = {'X-API-Key': _CIEMAT_API_KEY, 'Content-Type': 'application/json'}

    try:
        resp = requests.post(forecast_url, json={'lat': lat, 'lon': lon}, headers=headers,
                              timeout=_CIEMAT_FORECAST_TIMEOUT)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            logger.error('CIEMAT API returned non-JSON body (status %s): %s', resp.status_code, resp.text[:200])
            return JsonResponse({'error': 'The forecast service returned an unexpected response.'}, status=502)
        return JsonResponse({'points': data})
    except requests.Timeout:
        return JsonResponse({'error': 'The forecast service timed out. Please try again.'}, status=504)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        body = exc.response.text[:200] if exc.response is not None else ''
        if code in (401, 403):
            logger.error('CIEMAT API rejected credentials: status=%s', code)
            return JsonResponse({'error': 'The forecast service rejected the request credentials.'}, status=502)
        if 400 <= code < 500:
            logger.warning('CIEMAT API rejected forecast configuration: status=%s body=%s', code, body)
            return JsonResponse(
                {'error': 'The forecast service rejected the configuration. Check your inputs.'},
                status=422,
            )
        logger.error('CIEMAT API returned server error: status=%s body=%s', code, body)
        return JsonResponse({'error': 'The forecast service is temporarily unavailable.'}, status=502)
    except requests.RequestException:
        logger.exception('CIEMAT API request failed: url=%s', forecast_url)
        return JsonResponse({'error': 'Could not reach the forecast service.'}, status=502)


def _build_ciemat_calculate_payload(resolution, body):
    device_id = str(body.get('device_id', '')).strip()
    if not device_id:
        return None, 'A device ID is required.'

    timestamp = datetime.now(timezone.utc).isoformat()

    if resolution == 'solar':
        try:
            radiation = float(body['radiation'])
            t_ambiente = float(body['t_ambiente'])
        except (KeyError, TypeError, ValueError):
            return None, 'Invalid or missing solar input values.'
        return {
            'device_id': device_id,
            'timestamp': timestamp,
            'radiation': radiation,
            'T_ambiente': t_ambiente,
        }, None

    try:
        wind_speed = float(body['wind_speed'])
        rpm = float(body['rpm'])
        temperature = float(body['temperature'])
        pitch = float(body['pitch'])
    except (KeyError, TypeError, ValueError):
        return None, 'Invalid or missing wind input values.'

    payload = {
        'device_id': device_id,
        'timestamp': timestamp,
        'wind_speed': wind_speed,
        'rpm': rpm,
        'temperature': temperature,
        'pitch': pitch,
    }

    if resolution == '1s':
        try:
            payload['wind_speed_lag_5s'] = float(body['wind_speed_lag_5s'])
            payload['wind_speed_lag_10s'] = float(body['wind_speed_lag_10s'])
            payload['wind_speed_lag_20s'] = float(body['wind_speed_lag_20s'])
            payload['pitch_lag_5s'] = float(body['pitch_lag_5s'])
        except (KeyError, TypeError, ValueError):
            return None, 'Invalid or missing wind/pitch history values required for the 1-second model.'

    return payload, None


def _call_ciemat_calculate(resolution, payload):
    url = f'{_CIEMAT_API_BASE}/api/v1/{_CIEMAT_CALCULATE_ROUTES[resolution]}'
    headers = {'X-API-Key': _CIEMAT_API_KEY, 'Content-Type': 'application/json'}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_CIEMAT_CALCULATE_TIMEOUT)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            logger.error('CIEMAT API returned non-JSON body (status %s): %s', resp.status_code, resp.text[:200])
            return None, 'The calculation service returned an unexpected response.', 502
        try:
            return float(data), None, None
        except (TypeError, ValueError):
            logger.error('CIEMAT API returned a non-numeric power value: %r', data)
            return None, 'The calculation service returned an unexpected response.', 502
    except requests.Timeout:
        return None, 'The calculation service timed out. Please try again.', 504
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        body_text = exc.response.text[:200] if exc.response is not None else ''
        if code in (401, 403):
            logger.error('CIEMAT API rejected credentials: status=%s', code)
            return None, 'The calculation service rejected the request credentials.', 502
        if 400 <= code < 500:
            logger.warning('CIEMAT API rejected calculate input: status=%s body=%s', code, body_text)
            return None, 'The calculation service rejected the input values.', 422
        logger.error('CIEMAT API returned server error: status=%s body=%s', code, body_text)
        return None, 'The calculation service is temporarily unavailable.', 502
    except requests.RequestException:
        logger.exception('CIEMAT API request failed: url=%s', url)
        return None, 'Could not reach the calculation service.', 502


@login_required
@require_POST
def ciemat_calculate(request):
    if not check_rate_limit(request.user.pk, 'ciemat_calc'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another calculation.'}, status=429)

    if not _CIEMAT_API_KEY:
        return JsonResponse({'error': 'The CIEMAT forecasting service is not configured yet.'}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    resolution = body.get('resolution')
    if resolution not in _CIEMAT_CALCULATE_ROUTES:
        return JsonResponse({'error': 'Invalid resolution.'}, status=400)

    payload, error = _build_ciemat_calculate_payload(resolution, body)
    if error:
        return JsonResponse({'error': error}, status=400)

    power, error, status = _call_ciemat_calculate(resolution, payload)
    if error:
        return JsonResponse({'error': error}, status=status)

    return JsonResponse({'power_w': power, 'timestamp': payload['timestamp']})


@login_required
@require_POST
def ciemat_compare(request):
    if not check_rate_limit(request.user.pk, 'ciemat_compare'):
        return JsonResponse({'error': 'Too many requests. Please wait before running another comparison.'}, status=429)

    if not _CIEMAT_API_KEY:
        return JsonResponse({'error': 'The CIEMAT forecasting service is not configured yet.'}, status=503)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    resolutions = ('1min', '5min', '1s')
    payloads = {}
    for resolution in resolutions:
        payload, error = _build_ciemat_calculate_payload(resolution, body)
        if error:
            return JsonResponse({'error': error}, status=400)
        payloads[resolution] = payload

    # The three resolutions are independent calls against the same service,
    # so run them concurrently instead of paying up to 3x _CIEMAT_CALCULATE_TIMEOUT.
    with ThreadPoolExecutor(max_workers=len(resolutions)) as executor:
        futures = {
            resolution: executor.submit(_call_ciemat_calculate, resolution, payloads[resolution])
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


@login_required
def rdn_grid_dt(request):
    return dt_render(
        request, 'digitaltwins/rdn-grid-dt.html',
        use_cases=RDN_USE_CASES,
        locked_use_cases=RDN_LOCKED_USE_CASES,
        grid_sections=RDN_GRID_SECTIONS,
        asset_types=RDN_ASSET_TYPES,
        max_assets=_RDN_MAX_ASSETS,
        max_setpoints=_RDN_MAX_SETPOINTS,
    )


_RDN_RUNS_PAGE_SIZE = 20


def _rdn_job_duration_label(job):
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
    paginator = Paginator(jobs, _RDN_RUNS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    for job in page_obj:
        job.duration_label = _rdn_job_duration_label(job)
        job.use_case_label = RDN_USE_CASES.get(job.use_case, job.use_case)

    return dt_render(request, 'digitaltwins/rdn-grid-runs.html', page_obj=page_obj)


def _rdn_assets_breakdown(assets_items):
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
        duration_label=_rdn_job_duration_label(job),
        assets_items=assets_items,
        assets_breakdown=_rdn_assets_breakdown(assets_items),
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
        return JsonResponse(job.result, safe=False)

    try:
        body, content_length = open_result_stream(job.result_key)
    except MinioUploadError:
        logger.exception('Could not read RDN result for request %s', rdn_request_id)
        return JsonResponse({'error': 'The result could not be retrieved.'}, status=502)

    def _stream():
        try:
            while True:
                chunk = body.read(RESULT_STREAM_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    response = StreamingHttpResponse(_stream(), content_type='application/json')
    if content_length is not None:
        response['Content-Length'] = content_length
    return response


@login_required
@require_POST
def rdn_grid_simulate(request):
    if not check_rate_limit(request.user.pk, 'rdn_grid', _RDN_SIMULATE_RATE_LIMIT, _RDN_SIMULATE_RATE_WINDOW):
        return JsonResponse({'error': 'Too many requests. Please wait before running another simulation.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    cleaned, error = _validate_rdn_grid_input(body)
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

    RdnSimulationJob.objects.filter(pk=job.pk).update(status=RdnSimulationJob.Status.RUNNING)
    async_task('digitaltwins.tasks.poll_rdn_job', job.pk)  # enqueued into qcluster, returns immediately

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


@login_required
@require_POST
def dt_save_result(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    twin_slug = body.get('twin_slug')
    if twin_slug not in _DT_BY_SLUG:
        return JsonResponse({'error': 'Invalid or missing twin_slug.'}, status=400)

    data = body.get('data')
    if not isinstance(data, dict):
        return JsonResponse({'error': 'Invalid or missing result data.'}, status=400)

    try:
        dt_result = save_simulation_result(twin_slug=twin_slug, user=request.user, data=data)
    except MinioUploadError as exc:
        logger.error('Failed to save DT result for user %s: %s', request.user.pk, exc)
        return JsonResponse({'error': 'Could not save the result.'}, status=502)

    minio_prefix = dt_result.result_key.rsplit('/', 1)[0]
    dataset_local_name = minio_prefix.rsplit('/', 1)[1]

    # JupyterHub identifies users by email (OAuth), so the provision server
    # must use the email as the username to land files in the right directory.
    jupyterhub_username = request.user.email

    try:
        provision_user_datasets(jupyterhub_username, {minio_prefix: dataset_local_name})
    except requests.RequestException as exc:
        logger.error('Failed to provision DT result into JupyterHub for user %s: %s', request.user.pk, exc)
        return JsonResponse({'error': 'The result was saved, but could not be opened in JupyterHub.'}, status=502)

    jupyterhub_url = settings.JUPYTERHUB_URL.rstrip('/')
    redirect_url = f'{jupyterhub_url}/user/{jupyterhub_username}/lab'

    return JsonResponse({'redirect_url': redirect_url})


@login_required
def digitaltwins_detail(request, slug):
    digital_twin = _DT_BY_SLUG.get(slug)
    if digital_twin is None:
        raise Http404
    return dt_render(request, f'digitaltwins/{slug}.html', digital_twin=digital_twin)
