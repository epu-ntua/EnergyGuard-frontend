"""Client for the R&D Nester (RDN) Grid Digital Twin TEF API.

Mirrors RDN's own reference `user_client.py` workflow (login, upload input,
poll job status, download result) but headless (no interactive prompts) and
in-memory (no local files), since this runs inside a Django view and a
django_q worker rather than as a standalone script.
"""

import gzip
import io
import json

import requests
from django.conf import settings
from django.core.cache import cache

_TOKEN_CACHE_KEY = 'rdn_api_token'
_TOKEN_CACHE_TTL = 600  # conservative vs. an unknown real JWT lifetime; a 401 forces re-login regardless
_REQUEST_TIMEOUT = 30
_UPLOAD_TIMEOUT = 60
_DOWNLOAD_TIMEOUT = 1800


class RdnApiError(RuntimeError):
    pass


def _api_url(path):
    return f"{settings.RDN_API_URL}/{path.lstrip('/')}"


def _login():
    response = requests.post(
        _api_url('auth/login'),
        data={'username': settings.RDN_API_EMAIL, 'password': settings.RDN_API_PASSWORD},
        timeout=_REQUEST_TIMEOUT,
    )
    if not response.ok:
        raise RdnApiError(f'RDN login failed: HTTP {response.status_code} - {response.text}')
    try:
        token = response.json()['access_token']
    except (ValueError, KeyError) as exc:
        raise RdnApiError('RDN login response did not contain an access_token.') from exc
    cache.set(_TOKEN_CACHE_KEY, token, timeout=_TOKEN_CACHE_TTL)
    return token


def _get_rdn_token(force_refresh=False):
    if not force_refresh:
        token = cache.get(_TOKEN_CACHE_KEY)
        if token:
            return token
    return _login()


def _request_with_reauth(method, path, **kwargs):
    """Issue an authenticated request, transparently re-logging in once on a 401."""
    token = _get_rdn_token()
    response = requests.request(method, _api_url(path), headers={'Authorization': f'Bearer {token}'}, **kwargs)
    if response.status_code == 401:
        token = _get_rdn_token(force_refresh=True)
        response = requests.request(method, _api_url(path), headers={'Authorization': f'Bearer {token}'}, **kwargs)
    return response


def upload_rdn_input(payload):
    """Upload a Digital Twin input JSON payload to RDN and create the simulation job.

    Raises RdnApiError on any failure, including HTTP 409 ("input already exists") -
    this should not happen given our DB-generated, globally-unique requestId, so a 409
    is treated as an unexpected condition rather than silently reused.
    """
    body_bytes = json.dumps(payload).encode('utf-8')
    try:
        response = _request_with_reauth(
            'POST', 'inputs/upload',
            files={'file': ('input.json', body_bytes, 'application/json')},
            timeout=_UPLOAD_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RdnApiError(f'Could not reach the RDN API to upload the input: {exc}') from exc

    if response.status_code == 409:
        raise RdnApiError(f'RDN reported the input/requestId as already existing: {response.text}')
    if not response.ok:
        raise RdnApiError(f'RDN input upload failed: HTTP {response.status_code} - {response.text}')


def get_rdn_job_status(request_id):
    try:
        response = _request_with_reauth('GET', f'jobs/{request_id}/status', timeout=_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise RdnApiError(f'Could not reach the RDN API to check job status: {exc}') from exc

    if not response.ok:
        raise RdnApiError(f'RDN job status check failed: HTTP {response.status_code} - {response.text}')
    try:
        return response.json()
    except ValueError as exc:
        raise RdnApiError('RDN job status response was not valid JSON.') from exc


def _download_s3_result(request_id):
    try:
        response = _request_with_reauth('GET', f'results/{request_id}/download-url', timeout=_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise RdnApiError(f'Could not reach the RDN API for the result download URL: {exc}') from exc

    if response.status_code in (404, 409):
        return None  # no S3 result pointer yet - caller falls back to the legacy endpoint
    if not response.ok:
        raise RdnApiError(f'RDN result download-url request failed: HTTP {response.status_code} - {response.text}')

    try:
        download_url = response.json()['downloadUrl']
    except (ValueError, KeyError) as exc:
        raise RdnApiError('RDN download-url response did not contain a downloadUrl.') from exc

    try:
        download_response = requests.get(download_url, timeout=_DOWNLOAD_TIMEOUT)
        download_response.raise_for_status()
    except requests.RequestException as exc:
        raise RdnApiError(f'Could not download the RDN result from S3: {exc}') from exc

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(download_response.content)) as gz:
            return json.loads(gz.read().decode('utf-8'))
    except (OSError, ValueError) as exc:
        raise RdnApiError(f'Could not decompress/parse the RDN S3 result: {exc}') from exc


def _download_legacy_result(request_id):
    try:
        response = _request_with_reauth('GET', f'results/{request_id}', timeout=_DOWNLOAD_TIMEOUT)
    except requests.RequestException as exc:
        raise RdnApiError(f'Could not reach the RDN API for the legacy result: {exc}') from exc

    if not response.ok:
        raise RdnApiError(f'RDN legacy result request failed: HTTP {response.status_code} - {response.text}')
    try:
        return response.json()
    except ValueError as exc:
        raise RdnApiError('RDN legacy result response was not valid JSON.') from exc


def download_rdn_result(request_id):
    """Download a completed RDN simulation result.

    Prefers the large S3-based workflow, falling back to the legacy inline JSON
    endpoint, mirroring RDN's own reference client's `try_download_result`.
    """
    result = _download_s3_result(request_id)
    if result is not None:
        return result
    return _download_legacy_result(request_id)
