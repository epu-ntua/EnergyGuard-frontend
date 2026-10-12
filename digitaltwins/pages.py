"""Pages shared by every twin (the list, each twin's overview, saving a result to
JupyterHub), and the twins that are pages only (CEA, CARTIF)."""

import json
import logging

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from core.services.object_storage import MinioUploadError
from datasets.models import Dataset
from datasets.services import provision_user_datasets
from datasets.services.pilot import pilot_object_folder

from .catalog import DIGITAL_TWINS, DT_BY_SLUG
from .common import dt_render
from .services import save_simulation_result

logger = logging.getLogger(__name__)

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


@login_required
def digitaltwins_list(request):
    return dt_render(request, 'digitaltwins/digitaltwins-list.html', digital_twins=DIGITAL_TWINS)


@login_required
def digitaltwins_detail(request, slug):
    digital_twin = DT_BY_SLUG.get(slug)
    if digital_twin is None:
        raise Http404
    return dt_render(request, f'digitaltwins/{slug}.html', digital_twin=digital_twin)


@login_required
def digitaltwins_pilot_dataset(request, slug):
    """A stable link to a twin's pilot dataset, the same in every environment.

    The pilot datasets are seeded separately on each machine, so their ids differ
    between a laptop and the server; a link by id is what forced the server to
    keep uncommitted edits to the overview templates. Access control is left to
    the dataset page this redirects to.
    """
    digital_twin = DT_BY_SLUG.get(slug)
    partner = (digital_twin or {}).get('pilot_partner')
    if not partner:
        raise Http404

    # Two markers, as in datasets.services.pilot.pilot_partner_for: the seeded
    # metadata key, or the export's MinIO folder. The folder matters because the
    # metadata of some pilot datasets has since been replaced by their signal
    # dictionary, dropping the key; the file is still the partner's export.
    dataset = Dataset.objects.filter(
        Q(metadata__pilot_partner=partner) | Q(data_file__startswith=f'{pilot_object_folder(partner)}/'),
    ).order_by('pk').only('pk').first()
    if dataset is None:
        messages.info(request, f"The pilot dataset of {digital_twin['name']} isn't available yet.")
        return redirect('datasets_list')
    return redirect('dataset_details', dataset_id=dataset.pk)


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
@require_POST
def dt_save_result(request):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    twin_slug = body.get('twin_slug')
    if twin_slug not in DT_BY_SLUG:
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
