"""Client for CIEMAT's forecasting/calculation API.

Each call returns (data, error, status): the data, or a user-facing error message
with the HTTP status the view should answer with.
"""

import logging
from datetime import datetime, timezone

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_FORECAST_TIMEOUT = 30   # seconds
_CALCULATE_TIMEOUT = 15  # seconds

CALCULATE_ROUTES = {
    '1s':    'calculate/1s',
    '1min':  'calculate/1min',
    '5min':  'calculate/5min',
    'solar': 'calculate/solar',
}


def is_configured():
    return bool(settings.CIEMAT_API_KEY)


def _url(path):
    return f"{settings.CIEMAT_API_BASE_URL.rstrip('/')}/api/v1/{path}"


def _headers():
    return {'X-API-Key': settings.CIEMAT_API_KEY, 'Content-Type': 'application/json'}


def forecast(generation_type, lat, lon):
    forecast_url = _url(f'forecast/{generation_type}')
    try:
        resp = requests.post(forecast_url, json={'lat': lat, 'lon': lon}, headers=_headers(),
                             timeout=_FORECAST_TIMEOUT)
        resp.raise_for_status()
        try:
            return resp.json(), None, None
        except ValueError:
            logger.error('CIEMAT API returned non-JSON body (status %s): %s', resp.status_code, resp.text[:200])
            return None, 'The forecast service returned an unexpected response.', 502
    except requests.Timeout:
        return None, 'The forecast service timed out. Please try again.', 504
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        body = exc.response.text[:200] if exc.response is not None else ''
        if code in (401, 403):
            logger.error('CIEMAT API rejected credentials: status=%s', code)
            return None, 'The forecast service rejected the request credentials.', 502
        if 400 <= code < 500:
            logger.warning('CIEMAT API rejected forecast configuration: status=%s body=%s', code, body)
            return None, 'The forecast service rejected the configuration. Check your inputs.', 422
        logger.error('CIEMAT API returned server error: status=%s body=%s', code, body)
        return None, 'The forecast service is temporarily unavailable.', 502
    except requests.RequestException:
        logger.exception('CIEMAT API request failed: url=%s', forecast_url)
        return None, 'Could not reach the forecast service.', 502


def build_calculate_payload(resolution, body):
    """The API payload for one resolution's model, or (None, error) for invalid input."""
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


def calculate(resolution, payload):
    url = _url(CALCULATE_ROUTES[resolution])
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=_CALCULATE_TIMEOUT)
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
