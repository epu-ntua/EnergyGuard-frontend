import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import mail_admins
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

# Phoenix theme colors used by the AI model cards/badges (var(--phoenix-<color>)).
ALLOWED_COLORS = {'primary', 'secondary', 'success', 'info', 'warning', 'danger', 'dark'}

# What each model does, for the AI Models Inventory chart on the dashboard. One category per model.
CATEGORY_LABELS = {
    'forecasting': 'Forecasting',
    'anomaly_detection': 'Anomaly Detection',
    'optimization': 'Economic Simulation',
}

AI_MODELS = [
    {
        'slug': 'smart-energy-optimiser',
        'name': 'Smart Energy Optimiser',
        'description': 'Predicts solar power output from weather and plant configuration.',
        'category': 'forecasting',
        'details': "Estimates how much electricity a photovoltaic plant will produce over a given period, "
                   "and how that production splits between energy fed into the grid and energy self-consumed "
                   "on-site. It combines real and historical weather data with the plant's physical "
                   "characteristics (panel count, tilt, azimuth) to produce short-term (1-16 day), historical "
                   "baseline, and optimistic clear-sky forecasts.",
        'color': 'primary',
        'image': 'assets/img/ai-models/thumbs/pv-generation-forecasting.webp',
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
        'slug': 'renewable-generation-forecasting',
        'name': 'Renewable Generation Forecasting',
        'description': 'Forecasts wind and solar power output at the CEDER-CIEMAT microgrid.',
        'category': 'forecasting',
        'details': 'The Renewable Generation Forecasting Service is a CIEMAT node service, provided by the '
                   'EnergyPrediction application, that estimates wind and photovoltaic power output at the '
                   'CEDER-CIEMAT microgrid. It offers three complementary modes: 5-day weather-based '
                   'forecasting, real-time power calculation from live measurements, and a model comparator '
                   'that evaluates the multilag wind model against the base models.',
        'color': 'secondary',
        'image': 'assets/img/ai-models/renewable-focecast.jpg',
        'cta_url_name': 'ciemat-forecasting-dt',
        'getting_started': [
            'Choose a generation type: wind power (NED100 turbine model) or photovoltaic (Afrisol reference plant).',
            'Select a mode: 5-day forecast, real-time calculation, or model comparator.',
            'For the 5-day forecast, set a location within Spain; for the other modes, provide live sensor measurements.',
        ],
        'modes': [
            {'title': '5-Day Forecast', 'badge': '5 DAYS', 'badge_color': 'info',
             'description': 'Predicts wind or PV output over the next five days for a location, combining '
                             'Open-Meteo weather forecasts with a machine-learning correction model.'},
            {'title': 'Real-Time Calculation', 'badge': 'LIVE', 'badge_color': 'warning',
             'description': 'Calculates instantaneous wind or PV power output from live measurements, at '
                             '1-second, 1-minute or 5-minute resolution for wind.'},
            {'title': 'Model Comparator', 'badge': 'WIND ONLY', 'badge_color': 'success',
             'description': 'Evaluates the wind multilag model (1-second) against the base models (1-minute, '
                             '5-minute) using the same measurements.'},
        ],
        'after_simulation': "You'll see KPIs (total energy, peak power, generating hours) and a power output "
                             "chart, and you can export the results as JSON or save them to JupyterHub.",
    },
    {
        'slug': 'fair-dynamic-pricing',
        'name': 'Fair Dynamic Pricing',
        'description': 'Economically evaluates different energy consumption and sharing scenarios within the REC.',
        'category': 'optimization',
        'details': 'Supports the assessment of the economic effects of different consumption patterns, shared '
                   'energy levels and incentive-related scenarios, helping to evaluate how pricing or '
                   'behavioural strategies may affect REC performance.',
        'color': 'info',
        'image': 'assets/img/ai-models/thumbs/fair-dynamic-pricing.webp',
    },
    {
        'slug': 'predictive-maintenance-monitoring',
        'name': 'Predictive Maintenance Monitoring',
        'description': 'Detects anomalous operating patterns in monitored photovoltaic plants.',
        'category': 'anomaly_detection',
        'details': 'Identifies abnormal operating hours and supports the interpretation of possible local asset '
                   'issues, such as communication losses, abnormal inverter behaviour, shading, degradation or '
                   'battery-related effects.',
        'color': 'success',
        'image': 'assets/img/ai-models/thumbs/predictive-maintenance-monitoring.webp',
    },
    {
        'slug': 'deeptsf',
        'name': 'DeepTSF',
        'description': 'Deep learning-based time series forecasting for energy data.',
        'category': 'forecasting',
        'color': 'dark',
        'image': 'assets/img/ai-models/logo-deeptsf.png',
        'request_access': True,
        'compact': True,
    },
    {
        'slug': 'tirex',
        'name': 'Tirex',
        'description': 'Time series forecasting API server for energy data.',
        'category': 'forecasting',
        'details': 'Tirex is a forecasting model server hosted on EnergyGuard, exposing a REST API with '
                   'endpoints for mean and quantile time series forecasts, used internally by other '
                   'EnergyGuard AI models.',
        'color': 'primary',
        'cta_url': 'https://tirex.energy-guard.eu/docs',
        'cta_label': 'View API Docs',
        'cta_external': True,
    },
    {
        'slug': 'chronos',
        'name': 'Chronos-2',
        'description': 'Time series foundation model for probabilistic forecasting.',
        'category': 'forecasting',
        'details': 'A FastAPI service exposing Amazon Chronos-2, a time series foundation model, to generate '
                   'probabilistic forecasts over multiple time series with optional past and future '
                   'covariates and configurable quantile levels.',
        'color': 'warning',
        'cta_url': 'https://github.com/epu-ntua/Chronos2-inference-server',
        'cta_label': 'View on GitHub',
        'cta_external': True,
    },

]


def _validate_ai_models(models):
    seen_slugs = set()
    for model in models:
        slug = model.get('slug')
        if not slug or slug in seen_slugs:
            raise ImproperlyConfigured(f"AI_MODELS has a missing or duplicate slug: {slug!r}")
        seen_slugs.add(slug)

        color = model.get('color')
        if color not in ALLOWED_COLORS:
            raise ImproperlyConfigured(
                f"AI_MODELS['{slug}'] has an invalid color {color!r}; must be one of {sorted(ALLOWED_COLORS)}"
            )

        category = model.get('category')
        if category not in CATEGORY_LABELS:
            raise ImproperlyConfigured(
                f"AI_MODELS['{slug}'] has an invalid category {category!r}; "
                f"must be one of {sorted(CATEGORY_LABELS)}"
            )

        cta_url = model.get('cta_url')
        if cta_url and not cta_url.startswith('http'):
            raise ImproperlyConfigured(f"AI_MODELS['{slug}'] has a malformed cta_url: {cta_url!r}")


_validate_ai_models(AI_MODELS)


@login_required
def ai_models(request):
    models = []
    for model in AI_MODELS:
        model = dict(model)
        cta_url_name = model.pop('cta_url_name', None)
        if cta_url_name:
            try:
                model['cta_url'] = reverse(cta_url_name)
            except NoReverseMatch:
                logger.exception(
                    "AI model '%s' references an unknown URL name '%s'; hiding its workspace link",
                    model['slug'], cta_url_name,
                )

        model['has_modal'] = bool(model.get('cta_url') or model.get('request_access'))
        model.setdefault('compact', False)
        models.append(model)

    return render(request, 'core/ai-models.html', {
        'show_sidebar': True,
        'active_navbar_page': 'ai_models',
        'ai_models': models,
    })


@login_required
@require_POST
def request_ai_model_access(request):
    slug = request.POST.get('model_slug', '')
    model = next((m for m in AI_MODELS if m['slug'] == slug), None)

    if model is None:
        messages.error(request, "Unknown AI model.")
        return redirect('ai_models')

    user_name = request.user.get_full_name() or request.user.email
    try:
        mail_admins(
            subject=f"[EnergyGuard] Access request for {model['name']}",
            message=(
                f"{user_name} ({request.user.email}) has requested access to "
                f"the AI model '{model['name']}' on EnergyGuard.\n\n"
                f"Team: {getattr(getattr(request.user, 'profile', None), 'team', None) or 'N/A'}"
            ),
        )
        messages.success(request, f"Your request for access to {model['name']} has been sent to the admins.")
    except Exception:
        logger.exception("Failed to send access request email for model %s from user %s", slug, request.user.email)
        messages.error(request, "Could not send your access request. Please try again later.")

    return redirect('ai_models')
