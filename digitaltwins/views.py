from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

DIGITAL_TWINS = [
    {
        'slug': 'portuguese-grid',
        'name': 'Large-Scale Portuguese Transmission Network',
        'description': "A comprehensive Digital Twin of Portugal's large-scale transmission grid, designed to support power systems with high shares of renewable energy.",
    },
    {
        'slug': 'ceder-microgrid',
        'name': 'CEDER-CIEMAT Microgrid with Distributed Energy Resources',
        'description': 'A real renewable microgrid with solar, wind, storage, and hydrogen integration, supported by a Digital Twin for testing intelligent energy management strategies.',
    },
    {
        'slug': 'hydrogen-platforms',
        'name': 'Hydrogen Testing Platforms at CEA, CARTIF, BER & CIEMAT',
        'description': 'Advanced hydrogen facilities and electrolysis systems for testing hydrogen technologies across four European centers.',
    },
    {
        'slug': 'riga',
        'name': "Riga's Multi-Apartment Residential Buildings",
        'description': "A city-scale Digital Twin of Riga's residential buildings, supporting energy efficiency analysis and renovation planning.",
    },
    {
        'slug': 'antrodoco',
        'name': 'Antrodoco Renewable Energy Community',
        'description': 'A renewable energy community, digitally modelled for community-level energy management and optimization.',
    },
]

_DT_BY_SLUG = {dt['slug']: dt for dt in DIGITAL_TWINS}


@login_required
def map_view(request):
    return render(request, 'digitaltwins/map.html', {'show_sidebar': True})


@login_required
def digitaltwins_list(request):
    return render(request, 'digitaltwins/digitaltwins-list.html', {
        'show_sidebar': True,
        'active_navbar_page': 'facilities',
        'digital_twins': DIGITAL_TWINS,
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
