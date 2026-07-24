import bisect
import json
import logging
import math
import random
import re
from datetime import datetime, timezone
from functools import lru_cache
from math import ceil
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.services.object_storage import MinioUploadError
from datasets.services import provision_user_datasets

from .services import save_simulation_result

logger = logging.getLogger(__name__)

_HAL_BASE = settings.HAL_BASE_URL
_VALID_PROFILES = {'away_during_day', 'mixed_use', 'often_home'}

_SIMULATE_RATE_LIMIT = 20   # max requests per user per window
_SIMULATE_RATE_WINDOW = 60  # seconds

_HAL_STATIONS_TIMEOUT = 5   # seconds
_HAL_SIMULATE_TIMEOUT = 30  # seconds
_MAX_FORECAST_DAYS    = 16
_MAX_PANELS           = 50


def _check_simulate_rate_limit(user_id, prefix, limit=_SIMULATE_RATE_LIMIT, window=_SIMULATE_RATE_WINDOW):
    key = f'{prefix}_simulate_rl_{user_id}'
    count = cache.get(key, 0)
    if count >= limit:
        return False
    cache.set(key, count + 1, timeout=window)
    return True


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
        'slug': 'ceder-microgrid',
        'name': 'CEDER-CIEMAT Microgrid with Distributed Energy Resources',
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


# ── RDN Grid DT ──────────────────────────────────────────────────────────────
# RDN's real physics engine is external and not available to this platform, so
# the simulate endpoint below generates schema-conformant SYNTHETIC output. The
# shape matches RDN's real input/output JSON schemas exactly, so swapping the
# generator for a real call to RDN's API later only touches _generate_rdn_mock_output.

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
_RDN_MAX_OUTPUT_SAMPLES = 4_000_000  # guards response size/CPU for pathological requests

_RDN_NOMINAL_KV_BY_SECTION = {  # placeholder tiering matching rdn-grid.html's voltage classes
    'A': 400, 'B': 400, 'C': 220, 'D': 220, 'E': 150, 'F': 150, 'G': 150, 'All': 220,
}
_RDN_STEP_MS = 2
_RDN_MAX_SPAN_MS = 10_000            # output covers at most 10s per setpoint
_RDN_DEFAULT_LAST_RESOLUTION_MS = 900_000  # 15 min, used only when there's a single setpoint

_RDN_FOLLOW_CACHE_TTL = 3600  # seconds

_RDN_SIMULATE_RATE_LIMIT = 5  # lower than the default: mock generation is CPU-heavier
_RDN_SIMULATE_RATE_WINDOW = 60


def _user_organisation_name(user):
    try:
        team = user.profile.team
    except ObjectDoesNotExist:
        return 'Independent'
    return team.name if team else 'Independent'


def _iso_to_epoch_ms(ts):
    return int(datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp() * 1000)


def _validate_rdn_grid_input(body):
    if not isinstance(body, dict):
        return None, 'Request body must be a JSON object.'

    user_id = body.get('userId')
    user_organisation = body.get('userOrganisation')
    use_case = body.get('useCase')
    request_id = body.get('requestId')
    request_timestamp = body.get('requestTimestamp_UTC')
    follows_request_id = body.get('followsRequestId')
    input_data = body.get('inputData')

    if not isinstance(user_id, str) or not user_id.strip():
        return None, 'userId is required.'
    if not isinstance(user_organisation, str) or not user_organisation.strip():
        return None, 'userOrganisation is required.'
    if use_case not in RDN_USE_CASES:
        return None, 'useCase must be one of the supported automatic-interaction use cases.'
    if not isinstance(request_id, int) or isinstance(request_id, bool) or request_id < 1:
        return None, 'requestId must be an integer >= 1.'

    try:
        _iso_to_epoch_ms(request_timestamp)
    except (ValueError, TypeError):
        return None, 'requestTimestamp_UTC must be an ISO-8601 UTC timestamp ending in Z.'

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
        return None, 'Request too large — reduce setpoints, assets, or resolution.'

    cleaned = {
        'userId': user_id,
        'userOrganisation': user_organisation,
        'useCase': use_case,
        'requestId': request_id,
        'requestTimestamp_UTC': request_timestamp,
        'followsRequestId': follows_request_id,
        'inputData': {'gridSection': grid_section, 'asset': cleaned_assets},
    }
    return cleaned, None


def _rdn_follow_cache_key(request_id):
    return f'rdn_follow_{request_id}'


def _store_rdn_follow(request_id, grid_section, use_case, assets):
    cache.set(
        _rdn_follow_cache_key(request_id),
        {'gridSection': grid_section, 'useCase': use_case, 'assets': assets},
        timeout=_RDN_FOLLOW_CACHE_TTL,
    )


def _load_rdn_follow(request_id):
    return cache.get(_rdn_follow_cache_key(request_id))


def _rdn_derive_resolution_ms(timestamps_ms, index):
    if index < len(timestamps_ms) - 1:
        return timestamps_ms[index + 1] - timestamps_ms[index]
    if len(timestamps_ms) > 1:
        return timestamps_ms[index] - timestamps_ms[index - 1]
    return _RDN_DEFAULT_LAST_RESOLUTION_MS


def _rdn_n_points_for_resolution(resolution_ms):
    span_ms = min(resolution_ms, _RDN_MAX_SPAN_MS)
    return max(1, round(span_ms / _RDN_STEP_MS))


def _rdn_transient(steady_value, amplitude, t_seconds, tau, freq_hz, phase_rad):
    return steady_value + amplitude * math.exp(-t_seconds / tau) * math.cos(2 * math.pi * freq_hz * t_seconds + phase_rad)


def _rdn_bus_series(mw, mvar, nominal_kv, n_points, rng):
    """Placeholder physics: a damped oscillation around a steady-state value
    derived from the setpoint. NOT a real power-flow/EMT solution."""
    mw = mw or 0.0
    mvar = mvar or 0.0
    apparent_mva = math.hypot(mw, mvar)

    dv_pu = max(-0.05, min(0.05, 0.0005 * mw))
    steady_v_kv = nominal_kv * (1 + dv_pu)
    steady_i_ka = apparent_mva / (math.sqrt(3) * steady_v_kv) if steady_v_kv else 0.0

    v_amp = steady_v_kv * 0.005
    i_amp = steady_i_ka * 0.02
    tau_v, tau_i = 0.05, 0.08
    f_osc = 5.0

    phase_offsets = {'phase_a': 0.0, 'phase_b': -2 * math.pi / 3, 'phase_c': 2 * math.pi / 3}
    out = {}
    for phase_name, phase_offset in phase_offsets.items():
        v_series, i_series = [], []
        for k in range(n_points):
            t = k * (_RDN_STEP_MS / 1000.0)
            jitter_v = rng.uniform(-1, 1) * v_amp * 0.1
            jitter_i = rng.uniform(-1, 1) * i_amp * 0.1
            v_series.append(round(_rdn_transient(steady_v_kv, v_amp, t, tau_v, f_osc, phase_offset) + jitter_v, 4))
            i_series.append(round(_rdn_transient(steady_i_ka, i_amp, t, tau_i, f_osc, phase_offset) + jitter_i, 5))
        out[phase_name] = {'Voltage_kV': v_series, 'Current_kA': i_series}
    return out


def _rdn_frequency_series(total_imbalance_mw, n_points, rng):
    base_hz = 50.0
    d_hz = max(-0.2, min(0.2, -0.00005 * total_imbalance_mw))
    tau_f, f_osc = 2.0, 0.3
    noise_smoothing = 0.03  # lower = smoother, slower-wandering noise instead of per-sample jitter
    values = []
    noise = 0.0
    for k in range(n_points):
        noise += noise_smoothing * (rng.uniform(-1, 1) * 0.01 - noise)
        values.append(round(
            _rdn_transient(base_hz + d_hz, abs(d_hz) * 0.3, k * (_RDN_STEP_MS / 1000.0), tau_f, f_osc, 0.0) + noise,
            4,
        ))
    return values


def _generate_rdn_mock_output(cleaned_input):
    grid_section = cleaned_input['inputData']['gridSection']
    nominal_kv = _RDN_NOMINAL_KV_BY_SECTION[grid_section]
    assets = cleaned_input['inputData']['asset']
    request_id = cleaned_input['requestId']

    asset_ids = sorted(assets)
    timestamps = [item['timestamp_UTC'] for item in assets[asset_ids[0]]['assetTimeSeries']]
    timestamps_ms = [_iso_to_epoch_ms(ts) for ts in timestamps]

    output_data = []
    for idx, ts in enumerate(timestamps):
        resolution_ms = _rdn_derive_resolution_ms(timestamps_ms, idx)
        n_points = _rdn_n_points_for_resolution(resolution_ms)

        total_mw = sum((assets[aid]['assetTimeSeries'][idx].get('MW') or 0.0) for aid in asset_ids)

        grid_entry = {}
        for a_idx, aid in enumerate(asset_ids):
            asset = assets[aid]
            point = asset['assetTimeSeries'][idx]
            mw, mvar = point.get('MW'), point.get('MVAr')
            rng = random.Random(request_id * 1_000_000 + a_idx * 1000 + idx)
            grid_id = 'grid_' + aid.split('_', 1)[1]
            setpoint = {}
            if mw is not None:
                setpoint['MW'] = mw
            if mvar is not None:
                setpoint['MVAr'] = mvar
            grid_entry[grid_id] = {
                'BusType': asset['assetType'],
                'InputPowerSetpoint': setpoint,
                **_rdn_bus_series(mw, mvar, nominal_kv, n_points, rng),
            }

        freq_rng = random.Random(request_id * 1_000_000 + 999 * 1000 + idx)
        output_data.append({
            'InputTimestamp_UTC': ts,
            'GridFrequency_Hz': _rdn_frequency_series(total_mw, n_points, freq_rng),
            'grid': grid_entry,
        })

    return {
        'userId': cleaned_input['userId'],
        'useCase': cleaned_input['useCase'],
        'requestId': request_id,
        'timestamp_UTC': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'outputData': output_data,
    }


def _dt_render(request, template, **extra):
    return render(request, template, {'show_sidebar': True, 'active_navbar_page': 'facilities', **extra})


_BER_RESULTS_LP_PATH = Path(__file__).resolve().parent / 'static' / 'digitaltwins' / 'data' / 'ber-hydrogen-sample.lp'
_BER_EXPERIMENT_ID = 'BER-2026-000123'
_BER_SERIAL_NUMBER = 6
_BER_POWER_TAGS = ('JT_3001', 'JT_3002', 'JT_3003', 'ET_1001', 'IT_1101')
_BER_CHART_MAX_POINTS = 1500

BER_SIGNAL_INFO = {
    'JT_3001': {'label': 'Total power',        'unit': 'kW', 'description': "The total electrical power drawn by the whole system, including the stack and all auxiliary equipment (pumps, cooling, controls)."},
    'JT_3002': {'label': 'Stack power',         'unit': 'kW', 'description': 'The electrical power consumed by the electrolyzer stack itself, where hydrogen is actually produced.'},
    'JT_3003': {'label': 'Auxiliaries power',   'unit': 'kW', 'description': 'The power used by supporting equipment such as pumps, valves, and cooling, on top of the stack.'},
    'ET_1001': {'label': 'Stack voltage',       'unit': 'V',  'description': 'The electrical voltage across the electrolyzer stack while it operates.'},
    'IT_1101': {'label': 'Stack current',       'unit': 'A',  'description': 'The electrical current flowing through the stack. Together with voltage, it determines the power delivered to the stack.'},
}


@lru_cache(maxsize=1)
def _parse_ber_power_signals():
    series = {tag: [] for tag in _BER_POWER_TAGS}
    with open(_BER_RESULTS_LP_PATH, encoding='utf-8') as f:
        for line in f:
            if not line.startswith('power,'):
                continue
            parts = line.rstrip('\n').split(' ')
            if len(parts) != 3:
                continue
            tag, sep, raw_value = parts[1].partition('=')
            if not sep or tag not in series:
                continue
            try:
                value = float(raw_value)
                ts_seconds = int(parts[2]) / 1_000_000_000
            except ValueError:
                continue
            series[tag].append((ts_seconds, value))
    for tag in series:
        series[tag].sort(key=lambda point: point[0])
    return series


def _downsample(points, max_points=_BER_CHART_MAX_POINTS):
    n = len(points)
    if n <= max_points:
        return list(points)
    stride = ceil(n / max_points)
    sampled = points[::stride]
    if (n - 1) % stride != 0:
        sampled = list(sampled) + [points[-1]]
    return list(sampled)


def _forward_fill(points, timestamps):
    """Sample a step-wise (last-known-value) series at the given timestamps."""
    ts_list = [ts for ts, _ in points]
    values = [value for _, value in points]
    result = []
    for t in timestamps:
        i = bisect.bisect_right(ts_list, t) - 1
        result.append(values[i] if i >= 0 else values[0])
    return result


def _aligned_stacked_series(series, tags, max_points=_BER_CHART_MAX_POINTS):
    """Resample several tags onto one shared timestamp grid so their values can be
    stacked (summed) correctly in a stacked area chart, even though each tag was
    originally logged at its own, differing sample rate."""
    merged_ts = sorted({ts for tag in tags for ts, _ in series[tag]})
    merged_ts = _downsample(merged_ts, max_points)
    return {
        tag: [[round(ts * 1000), round(value, 3)]
              for ts, value in zip(merged_ts, _forward_fill(series[tag], merged_ts))]
        for tag in tags
    }


def _format_duration(seconds):
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}h {minutes:02d}m'
    return f'{minutes}m {secs:02d}s'


def _compute_ber_kpis(series):
    def values(tag):
        return [value for _, value in series[tag]]

    return {
        'peak_total_power':   max(values('JT_3001'), default=0.0),
        'avg_stack_power':    (sum(values('JT_3002')) / len(series['JT_3002'])) if series['JT_3002'] else 0.0,
        'avg_aux_power':      (sum(values('JT_3003')) / len(series['JT_3003'])) if series['JT_3003'] else 0.0,
        'peak_stack_current': max(values('IT_1101'), default=0.0),
        'peak_stack_voltage': max(values('ET_1001'), default=0.0),
    }


def _build_ber_kpi_cards(kpis):
    return [
        {'label': 'Peak Total Power',   'value': kpis['peak_total_power'],   'unit': 'kW', 'value_class': 'text-body-emphasis'},
        {'label': 'Avg. Stack Power',   'value': kpis['avg_stack_power'],    'unit': 'kW', 'value_class': 'text-primary'},
        {'label': 'Avg. Aux Power',     'value': kpis['avg_aux_power'],      'unit': 'kW', 'value_class': 'text-turquoise'},
        {'label': 'Peak Stack Current', 'value': kpis['peak_stack_current'], 'unit': 'A',  'value_class': 'text-body-emphasis'},
        {'label': 'Peak Stack Voltage', 'value': kpis['peak_stack_voltage'], 'unit': 'V',  'value_class': 'text-body-emphasis'},
    ]


def _power_chart_axis_range(peak_total_power, step=2):
    """Round up to the next multiple of `step` above the peak so the power chart's
    Y axis renders a consistent 0, step, 2*step, ... grid (instead of amCharts'
    auto-rounded one), with one step of headroom if the peak lands exactly on max."""
    axis_max = ceil(peak_total_power / step) * step
    if axis_max <= peak_total_power:
        axis_max += step
    return {'min': 0, 'max': axis_max}


@login_required
def ber_hydrogen_results(request):
    series = _parse_ber_power_signals()

    all_timestamps = [ts for points in series.values() for ts, _ in points]
    if not all_timestamps:
        raise Http404('No BER result data available.')

    run_start = min(all_timestamps)
    run_end = max(all_timestamps)

    kpis = _compute_ber_kpis(series)

    def _chart_points(tag):
        return [[round(ts * 1000), round(value, 3)] for ts, value in _downsample(series[tag])]

    chart_power = _aligned_stacked_series(series, ('JT_3002', 'JT_3003'))
    chart_electrical = {tag: _chart_points(tag) for tag in ('ET_1001', 'IT_1101')}
    chart_power_axis = _power_chart_axis_range(kpis['peak_total_power'])

    run_timestamp = datetime.fromtimestamp(run_start, tz=timezone.utc)
    duration_label = _format_duration(run_end - run_start)
    result_meta = {
        'experiment_id': _BER_EXPERIMENT_ID,
        'serial_number': _BER_SERIAL_NUMBER,
        'run_timestamp': run_timestamp.isoformat(),
        'duration_label': duration_label,
    }

    return _dt_render(
        request, 'digitaltwins/ber-hydrogen-results.html',
        experiment_id=_BER_EXPERIMENT_ID,
        serial_number=_BER_SERIAL_NUMBER,
        run_timestamp=run_timestamp,
        duration_label=duration_label,
        signal_info=BER_SIGNAL_INFO,
        kpis=kpis,
        kpi_cards=_build_ber_kpi_cards(kpis),
        result_meta=result_meta,
        chart_power=chart_power,
        chart_power_axis=chart_power_axis,
        chart_electrical=chart_electrical,
    )


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
    stations = _fetch_engreen_stations()
    if stations is None:
        return JsonResponse({'error': 'Could not load stations.'}, status=503)
    return JsonResponse(stations)


@login_required
@require_POST
def engreen_pv_simulate(request):
    if not _check_simulate_rate_limit(request.user.pk, 'engreen'):
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
def rdn_grid_dt(request):
    return _dt_render(
        request, 'digitaltwins/rdn-grid-dt.html',
        use_cases=RDN_USE_CASES,
        locked_use_cases=RDN_LOCKED_USE_CASES,
        grid_sections=RDN_GRID_SECTIONS,
        asset_types=RDN_ASSET_TYPES,
        max_assets=_RDN_MAX_ASSETS,
        max_setpoints=_RDN_MAX_SETPOINTS,
        rdn_user_id=request.user.email,
        rdn_user_organisation=_user_organisation_name(request.user),
    )


@login_required
@require_POST
def rdn_grid_simulate(request):
    if not _check_simulate_rate_limit(request.user.pk, 'rdn_grid', _RDN_SIMULATE_RATE_LIMIT, _RDN_SIMULATE_RATE_WINDOW):
        return JsonResponse({'error': 'Too many requests. Please wait before running another simulation.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    cleaned, error = _validate_rdn_grid_input(body)
    if error:
        return JsonResponse({'error': error}, status=400)

    try:
        result = _generate_rdn_mock_output(cleaned)
    except Exception:
        logger.exception('RDN mock generation failed for request %s', cleaned.get('requestId'))
        return JsonResponse({'error': 'Could not generate the simulation result.'}, status=500)

    _store_rdn_follow(
        cleaned['requestId'],
        cleaned['inputData']['gridSection'],
        cleaned['useCase'],
        {aid: a['assetType'] for aid, a in cleaned['inputData']['asset'].items()},
    )

    return JsonResponse(result)


@login_required
def rdn_grid_follow_lookup(request):
    try:
        request_id = int(request.GET.get('requestId', ''))
    except ValueError:
        return JsonResponse({'error': 'Invalid requestId.'}, status=400)
    prior = _load_rdn_follow(request_id)
    if prior is None:
        return JsonResponse({'found': False})
    return JsonResponse({'found': True, **prior})


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
    return _dt_render(request, f'digitaltwins/{slug}.html', digital_twin=digital_twin)
