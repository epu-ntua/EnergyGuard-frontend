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
        'getting_started': [
            'Select an existing REC station or define a new hypothetical plant (panels, power, tilt, orientation).',
            'Choose a consumption profile that reflects how the household typically uses energy.',
            'Select your simulation type and, for short-term forecast, set the number of days ahead.',
        ],
        'modes': [
            {'title': 'Short-term forecast', 'badge': '1-16 DAYS', 'badge_color': 'info',
             'description': 'Predicts daily and hourly production for the next 1-16 days using real weather '
                             'forecast data.'},
            {'title': 'Historical baseline', 'badge': '5-YEAR AVG', 'badge_color': 'warning',
             'description': 'Estimates the typical annual yield averaged over the last 5 years of observed '
                             'weather.'},
            {'title': 'Optimistic scenario', 'badge': 'CLEAR-SKY', 'badge_color': 'success',
             'description': 'Estimates the theoretical maximum annual yield under ideal clear-sky conditions.'},
        ],
        'after_simulation': "You'll see a summary of total production, energy fed into the grid, and "
                             "self-consumed energy — broken down by day, hour, or month depending on the "
                             "scenario.",
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
