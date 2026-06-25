from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

DIGITAL_TWINS = [
    {
        'slug': 'portuguese-grid',
        'name': 'Large-Scale Portuguese Transmission Network',
        'description': "A comprehensive Digital Twin of Portugal's large-scale transmission grid, designed to support power systems with high shares of renewable energy.",
        'image': 'assets/img/digital_twins/RDN.png',
    },
    {
        'slug': 'ceder-microgrid',
        'name': 'CEDER-CIEMAT Microgrid with Distributed Energy Resources',
        'description': 'A real renewable microgrid with solar, wind, storage, and hydrogen integration, supported by a Digital Twin for testing intelligent energy management strategies.',
        'image': 'assets/img/digital_twins/Ceder-Lubia.jpg',
    },
    {
        'slug': 'hydrogen-platforms',
        'name': 'Hydrogen Testing Platforms at CEA, CARTIF, CIEMAT',
        'description': 'Advanced hydrogen facilities and electrolysis systems for testing hydrogen technologies across four European centers.',
        'image': 'assets/img/digital_twins/hydrogenCEA.jpg',
    },
    {
        'slug': 'ber-hydrogen',
        'name': 'BER Node — PEM Electrolyzer Testing Facility',
        'description': 'Physical PEM Electrolyzer Testing Facility. Experiments are executed manually by the BER laboratory team.',
        'image': 'assets/img/digital_twins/BER.jpg',
    },
    {
        'slug': 'riga',
        'name': "Riga's Multi-Apartment Residential Buildings",
        'description': "A city-scale Digital Twin of Riga's residential buildings, supporting energy efficiency analysis and renovation planning.",
        'image': 'assets/img/digital_twins/REA.png',
    },
    {
        'slug': 'antrodoco',
        'name': 'Antrodoco Renewable Energy Community',
        'description': 'A renewable energy community, digitally modelled for community-level energy management and optimization.',
        'image': 'assets/img/digital_twins/antrodoco.png',
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


@login_required
def map_view(request):
    return render(request, 'digitaltwins/map.html', {'show_sidebar': True, 'active_navbar_page': 'facilities'})


@login_required
def digitaltwins_list(request):
    return render(request, 'digitaltwins/digitaltwins-list.html', {
        'show_sidebar': True,
        'active_navbar_page': 'facilities',
        'digital_twins': DIGITAL_TWINS,
    })


@login_required
def cea_node_workspace(request):
    return render(request, 'digitaltwins/cea-hydrogen-dt.html', {
        'show_sidebar': True,
        'active_navbar_page': 'facilities',
        'validation_checks': CEA_VALIDATION_CHECKS,
        'sample_json': CEA_SAMPLE_JSON,
    })


@login_required
def ber_hydrogen_dt(request):
    return render(request, 'digitaltwins/ber-hydrogen-dt.html', {
        'show_sidebar': True,
        'active_navbar_page': 'facilities',
        'validation_checks': BER_VALIDATION_CHECKS,
        'sample_json': BER_SAMPLE_JSON,
    })


@login_required
def digitaltwins_detail(request, slug):
    digital_twin = _DT_BY_SLUG.get(slug)
    if digital_twin is None:
        raise Http404
    return render(request, f'digitaltwins/{slug}.html', {
        'show_sidebar': True,
        'active_navbar_page': 'facilities',
        'digital_twin': digital_twin,
    })
