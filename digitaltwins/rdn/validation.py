"""What an RDN simulation request may contain, and the validation of a submitted one."""

import re
from datetime import datetime

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

MAX_ASSETS = 25          # well under the schema's 1000, kept usable in a hand-built form
MAX_SETPOINTS = 100      # == schema max
_MAX_OUTPUT_SAMPLES = 75_500_000  # matches the worst case allowed by MAX_ASSETS/MAX_SETPOINTS/_MAX_SPAN_MS

_STEP_MS = 2
_MAX_SPAN_MS = 10_000            # output covers at most 10s per setpoint
_DEFAULT_LAST_RESOLUTION_MS = 900_000  # 15 min, used only when there's a single setpoint


def _iso_to_epoch_ms(ts):
    return int(datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp() * 1000)


def validate_rdn_grid_input(body):
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
    if not isinstance(asset, dict) or not (1 <= len(asset) <= MAX_ASSETS):
        return None, f'inputData.asset must contain between 1 and {MAX_ASSETS} assets.'

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
        if not isinstance(series, list) or not (1 <= len(series) <= MAX_SETPOINTS):
            return None, f'Asset "{asset_id}" must have between 1 and {MAX_SETPOINTS} time-series points.'

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

    resolutions_ms = [_derive_resolution_ms(shared_timestamps_ms, i) for i in range(len(shared_timestamps_ms))]
    total_points = sum(_n_points_for_resolution(r) for r in resolutions_ms)
    total_samples = len(cleaned_assets) * 3 * 2 * total_points + total_points
    if total_samples > _MAX_OUTPUT_SAMPLES:
        return None, (
            f'Request too large: computed {total_samples:,} output samples, exceeding the '
            f'{_MAX_OUTPUT_SAMPLES:,}-sample limit. Reduce setpoints, assets, or resolution.'
        )

    cleaned = {
        'useCase': use_case,
        'followsRequestId': follows_request_id,
        'inputData': {'gridSection': grid_section, 'asset': cleaned_assets},
    }
    return cleaned, None


def _derive_resolution_ms(timestamps_ms, index):
    if index < len(timestamps_ms) - 1:
        return timestamps_ms[index + 1] - timestamps_ms[index]
    if len(timestamps_ms) > 1:
        return timestamps_ms[index] - timestamps_ms[index - 1]
    return _DEFAULT_LAST_RESOLUTION_MS


def _n_points_for_resolution(resolution_ms):
    span_ms = min(resolution_ms, _MAX_SPAN_MS)
    return max(1, round(span_ms / _STEP_MS))
