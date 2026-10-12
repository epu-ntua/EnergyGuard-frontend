"""Canned responses for the external HTTP APIs the twins call (RDN, CIEMAT, HAL, JupyterHub).

Tests patch `requests.get` / `requests.post` / `requests.request` themselves, not
names inside digitaltwins modules, so they keep working wherever the calling code lives.
"""

import json

import requests


def http_response(status=200, json_data=None, text=None, url='http://api.test/'):
    response = requests.models.Response()
    response.status_code = status
    response.url = url
    response.reason = 'OK' if status < 400 else 'Error'
    if json_data is not None:
        response._content = json.dumps(json_data).encode()
        response.headers['Content-Type'] = 'application/json'
    else:
        response._content = (text or '').encode()
    return response
