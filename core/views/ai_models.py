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
        'slug': 'fair-dynamic-pricing',
        'name': 'Fair Dynamic Pricing ',
        'description': 'Εconomically evaluates different energy consumption and sharing scenarios within the REC.',
        'details': 'Supports the assessment of the economic effects of different consumption patterns, \
            shared energy levels and incentive-related scenarios, helping to evaluate how pricing or behavioural strategies may affect REC performance. ',
        'color': 'info',
        'image': 'assets/img/ai-models/fair-dynamic-pricing.jpg',
    },
    {
        'slug': 'predictive-maintenance-monitoring',
        'name': 'Predictive Maintenance Monitoring',
        'description': 'Detects anomalous operating patterns in monitored photovoltaic plants.',
        'details': 'Identifies abnormal operating hours and supports the interpretation of possible local asset issues, \
            such as communication losses, abnormal inverter behaviour, shading, degradation or battery-related effects. ',
        'color': 'success',
        'image': 'assets/img/ai-models/predictive-maintenance-monitoring.jpg',
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
