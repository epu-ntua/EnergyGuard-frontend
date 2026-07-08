from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

AI_MODELS = [
    {
        'slug': 'pv-generation-forecasting',
        'name': 'PV Generation Forecasting',
        'description': 'Predicts solar power output from weather and plant configuration.',
        'details': "Estimates how much electricity a photovoltaic plant will produce over a given period, "
                   "and how that production splits between energy fed into the grid and energy self-consumed "
                   "on-site. It combines real and historical weather data with the plant's physical "
                   "characteristics (panel count, tilt, azimuth) to produce short-term (1-16 day), historical "
                   "baseline, and optimistic clear-sky forecasts.",
        'icon': 'fa-solar-panel',
        'color': 'primary',
        'image': 'assets/img/ai-models/pv-generation-forecasting.jpg',
        'cta_url_name': 'engreen-antrodoco-dt',
        'steps': [
            {'icon': 'fa-hand-pointer', 'color': 'primary', 'title': 'Select',
             'description': 'Choose a REC station or configure a new PV plant.'},
            {'icon': 'fa-sliders', 'color': 'info', 'title': 'Configure',
             'description': 'Set consumption profile and forecast horizon.'},
            {'icon': 'fa-play', 'color': 'success', 'title': 'Simulate',
             'description': 'The Digital Twin runs the forecast scenario.'},
            {'icon': 'fa-chart-line', 'color': 'warning', 'title': 'Results',
             'description': 'View production, feed-in, and self-consumption charts.'},
            {'icon': 'fa-download', 'color': 'info', 'title': 'Export',
             'description': 'Download raw data for further analysis.'},
        ],
    },
    {
        'slug': 'load-demand-forecasting',
        'name': 'Load Demand Forecasting',
        'description': 'Forecasts electricity consumption for buildings and communities.',
        'details': 'Learns consumption patterns from historical smart-meter and household profile data to '
                   'predict how much electricity a building or energy community will need, hour by hour. Used '
                   'to size PV and battery capacity, plan demand-response actions, and match local generation '
                   'with expected consumption.',
        'icon': 'fa-chart-line',
        'color': 'info',
    },
    {
        'slug': 'hydrogen-production-optimization',
        'name': 'Hydrogen Production Optimization',
        'description': 'Optimizes electrolyzer operation for efficient hydrogen output.',
        'details': 'Recommends electrolyzer operating setpoints (current, flow rates, control mode) that '
                   'balance available renewable power, hydrogen demand, and equipment degradation limits, so '
                   'hydrogen is produced when it is cheapest and most efficient to do so.',
        'icon': 'fa-flask',
        'color': 'success',
    },
    {
        'slug': 'battery-storage-optimization',
        'name': 'Battery Storage Optimization',
        'description': 'Schedules charge/discharge cycles to maximize storage value.',
        'details': "Decides when a battery should charge or discharge based on forecasted generation, "
                   "consumption, and electricity prices, aiming to maximize self-consumption and minimize "
                   "costs while respecting the battery's state-of-charge and cycling limits.",
        'icon': 'fa-battery-full',
        'color': 'warning',
    },
    {
        'slug': 'anomaly-detection',
        'name': 'Anomaly Detection',
        'description': 'Flags abnormal readings across connected energy assets.',
        'details': 'Continuously compares live sensor readings from connected assets (inverters, '
                   'electrolyzers, meters) against expected behaviour, flagging deviations that may indicate '
                   'faults, degradation, or miscalibration before they cause downtime.',
        'icon': 'fa-triangle-exclamation',
        'color': 'danger',
    },
    {
        'slug': 'energy-community-optimization',
        'name': 'Energy Community Optimization',
        'description': 'Balances production, storage and consumption across a community.',
        'details': "Coordinates production, storage, and consumption across all members of a renewable "
                   "energy community, allocating shared generation to maximize collective self-consumption "
                   "and reduce the community's net energy costs.",
        'icon': 'fa-people-group',
        'color': 'primary',
    },
]


@login_required
def ai_models(request):
    models = []
    for model in AI_MODELS:
        model = dict(model)
        cta_url_name = model.pop('cta_url_name', None)
        if cta_url_name:
            model['cta_url'] = reverse(cta_url_name)
        models.append(model)

    return render(request, 'core/ai-models.html', {
        'show_sidebar': True,
        'active_navbar_page': 'ai_models',
        'ai_models': models,
    })
