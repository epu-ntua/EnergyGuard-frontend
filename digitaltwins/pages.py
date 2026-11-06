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
from .common import check_rate_limit, dt_render
from .runs import overview
from .services import ResultNotFound, export_result
from .services.jupyterhub_export import is_export_source

logger = logging.getLogger(__name__)

_EXPORT_RATE_LIMIT = 10  # per user per minute (SIMULATE_RATE_WINDOW)

CEA_VALIDATION_CHECKS = [
    'All required variables present',
    'Correct data types and ranges',
    'Signals have the same length as timeStamp',
]


def _cea_variable(name, label, kind, unit, low, high, description):
    """One input of the CEA scenario: name is its key in the file, label what the
    scenario builder shows; high is None for an unbounded range."""
    return {
        'name': name, 'label': label, 'kind': kind, 'unit': unit, 'min': low, 'max': high,
        'range': f"[{low} : {'inf' if high is None else high}]", 'description': description,
    }


# The scenario's inputs, in file order: the 'signal' ones are arrays as long as
# timeStamp, the 'scalar' ones single values. Both the documentation table and the
# scenario builder read their units and ranges from here.
CEA_VARIABLES = [
    _cea_variable('timeStamp', 'Time', 'signal', 's', 0, None,
                  'Time vector of the scenario. Only needs a new entry when a signal changes value: each value '
                  'holds until the next timestamp, so a long unchanged period can be expressed with just its end time.'),
    _cea_variable('current', 'Current', 'signal', 'A', -100, 0,
                  'Electrical current to apply on each stack of the electrolyser.'),
    _cea_variable('voltageCell', 'Cell voltage', 'signal', 'V', 1.285, 1.3,
                  'Mean cell voltage of the stacks to maintain (used only when a current is applied).'),
    _cea_variable('temperatureHotbox', 'Hotbox temperature', 'signal', '°C', 700, 800,
                  'Temperature of the thermal enclosure of the stacks (used only when no current is applied).'),
    _cea_variable('steamConversion', 'Steam conversion', 'signal', '–', 0.4, 1,
                  'Percentage of steam inlet flowrate converted into electricity by the system.'),
    _cea_variable('fuelElectrode_ratioH2O', 'Fuel steam ratio', 'signal', '–', 0, 1,
                  'Percentage of steam in the gas mix at the inlet of the system.'),
    _cea_variable('fuelElectrode_flowrate', 'Fuel flow rate', 'signal', 'NL/min', 0, 200,
                  'Total flowrate at the inlet of the fuel side.'),
    _cea_variable('oxygenElectrode_flowrate', 'Air flow rate', 'signal', 'NL/min', 0, 200,
                  'Total flowrate at the inlet of the air side.'),
    _cea_variable('deltaP', 'Pressure difference', 'signal', 'mBar', 0, 100,
                  'Pressure difference between the air and the fuel electrode of the cells inside the stacks.'),
    *(_cea_variable(f'coef_degradPerf[{stack}]', f'Stack {stack} performance', 'scalar', '–', 0.5, 1.5,
                    f'Coefficient to modify the initial electro-chemical performance of stack {stack}.')
      for stack in range(1, 5)),
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
    """The twins, or with ?tab=runs the user's runs of all of them.

    Only the open tab is built: the twins tab is the catalog page every menu links
    to, so it does not pay for the runs queries.
    """
    if request.GET.get('tab') != 'runs':
        return dt_render(request, 'digitaltwins/digitaltwins-list.html', digital_twins=DIGITAL_TWINS, active_tab='twins')
    return dt_render(
        request, 'digitaltwins/digitaltwins-list.html',
        active_tab='runs', **overview.runs_tab_context(request.user, request.GET),
    )


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
    return dt_render(request, 'digitaltwins/cea-dt-simulation.html',
                     cea_variables=CEA_VARIABLES, sample_json=CEA_SAMPLE_JSON)


@login_required
def cea_dt_documentation(request):
    return dt_render(request, 'digitaltwins/cea-dt-simulation-documentation.html', cea_variables=CEA_VARIABLES,
                     validation_checks=CEA_VALIDATION_CHECKS, sample_json=CEA_SAMPLE_JSON)


@login_required
def cartif_hydrogen_dt(request):
    return dt_render(request, 'digitaltwins/cartif-hydrogen-dt.html')


@login_required
@require_POST
def dt_save_result(request):
    """Open one of the user's stored twin results in JupyterHub.

    The body names the result - {"source": "run" | "rdn" | "ber", "id": ...} - and
    the server copies the stored file; the result's data never comes from the browser.
    """
    # Each export can copy a large file (an RDN result runs to hundreds of MB).
    if not check_rate_limit(request.user.pk, 'dt_export', limit=_EXPORT_RATE_LIMIT):
        return JsonResponse({'error': 'Too many requests. Please wait before opening another result.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid request body.'}, status=400)

    source, source_id = body.get('source'), body.get('id')
    if not is_export_source(source) or not isinstance(source_id, int) or isinstance(source_id, bool):
        return JsonResponse({'error': 'Invalid or missing result reference.'}, status=400)

    try:
        export = export_result(user=request.user, source=source, source_id=source_id)
    except ResultNotFound:
        return JsonResponse({'error': 'Result not found.'}, status=404)
    except MinioUploadError as exc:
        logger.error('Failed to export %s result %s for user %s: %s', source, source_id, request.user.pk, exc)
        return JsonResponse({'error': 'Could not save the result.'}, status=502)

    minio_prefix = export.result_key.rsplit('/', 1)[0]
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
