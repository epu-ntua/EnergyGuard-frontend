"""Client for the HAL service behind the Engreen Antrodoco DT."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_STATIONS_TIMEOUT = 5   # seconds
_SIMULATE_TIMEOUT = 30  # seconds

_SIMULATE_PATHS = {
    'short-term': 'simulate',
    'historical': 'simulate/annual/historical',
    'optimistic': 'simulate/annual/optimistic',
}
FORECAST_TYPES = tuple(_SIMULATE_PATHS)


def _url(path):
    return f'{settings.HAL_BASE_URL}/{path}'


def fetch_stations():
    """HAL's station list, or None if it can't be had."""
    try:
        resp = requests.get(_url('stations'), timeout=_STATIONS_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning('Could not fetch stations from HAL. Reason: %s', exc)
        return None


def simulate(forecast_type, payload):
    """Run a PV simulation. Returns (data, error, status) like the CIEMAT client."""
    hal_url = _url(_SIMULATE_PATHS[forecast_type])
    try:
        resp = requests.post(hal_url, json=payload, timeout=_SIMULATE_TIMEOUT)
        resp.raise_for_status()
        try:
            return resp.json(), None, None
        except ValueError:
            logger.error('HAL returned non-JSON body (status %s): %s', resp.status_code, resp.text[:200])
            return None, 'The forecast service returned an unexpected response.', 502
    except requests.Timeout:
        return None, 'The forecast service timed out. Please try again.', 504
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 502
        if 400 <= code < 500:
            return None, 'The forecast service rejected the configuration. Check your inputs.', 422
        return None, 'The forecast service is temporarily unavailable.', 502
    except requests.RequestException:
        logger.exception('HAL request failed: url=%s', hal_url)
        return None, 'Could not reach the forecast service.', 502
