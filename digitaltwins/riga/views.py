import json
from functools import lru_cache
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from digitaltwins.common import dt_render

_RIGA_BUILDINGS_PATH = Path(__file__).resolve().parent.parent / 'static' / 'digitaltwins' / 'data' / 'DT_data.json'


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
