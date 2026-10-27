"""Guided journeys: step-by-step guides for common tasks on the platform.

Documentation only: a journey lists the steps to follow and links to the pages where
each one is done. Nothing is tracked.

A journey can open with a `scenario`: one or two sentences about a persona and what they
want to achieve. `icon` is its FontAwesome icon.

The order of JOURNEYS is the order of the cards, and each journey suggests the one after
it as its next journey.

Each step has a title, a short `body` (one paragraph per item), `optional` when the
journey works without it, an optional `link` to
the page where the step is done (`url_name` and optional `kwargs`, reversed when the
page is shown), an optional `code` sample, and an optional `result` saying what the
user sees afterwards.

A body paragraph can link inline: `[text](journey:<slug>)` links to another journey,
`[text](<url_name>)` to a page of the platform. The rest of the text is escaped.
"""

import logging
import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

JOURNEYS = [
    {
        'slug': 'first-experiment',
        'title': 'Your first experiment',
        'summary': 'Create a project, open a dataset in JupyterHub and track your first run in MLflow.',
        'scenario': (
            'Alice develops a tool that estimates how much energy a building could save with '
            "different renovation actions. Alice wants to train the tool's model on a dataset and "
            'keep track of every training run.'
        ),
        'icon': 'fa-flask',
        'audience': 'AI developers and data scientists',
        'duration': 'About 20 minutes',
        'tools': 'Projects, Datasets, JupyterHub, MLflow',
        'steps': [
            {
                'title': 'Create a project',
                'body': [
                    'A project groups your data, notebooks and tracked runs. Give it a name and choose '
                    'the project type that fits your work, for example AI Model.',
                ],
                'link': {'label': 'Add new project', 'url_name': 'project_creation'},
                'result': 'The project opens with a default MLflow experiment already created for it. '
                          'You can see the experiment in the project\'s Experiments table.',
            },
            {
                'title': 'Open your workspace in JupyterHub',
                'body': [
                    'On your project page, choose "Open in Jupyter". JupyterHub is your personal workspace, '
                    'where you write and run your code.',
                    'The EnergyGuard kernel is selected by default and comes with the Python packages you '
                    'need, so there is nothing to install.',
                ],
                'link': {'label': 'My projects', 'url_name': 'projects_list'},
            },
            {
                'title': 'Bring in a dataset',
                'optional': True,
                'body': [
                    'To train on data, open a dataset ([contribute your own](journey:contribute-dataset), '
                    'or choose a public one), '
                    'choose "Use in a Project", select your project and press Run.',
                    'The dataset is copied into the "datasets" folder of your workspace. That folder is '
                    'read-only: the original data can only be changed from the platform.',
                ],
                'link': {'label': 'Browse datasets', 'url_name': 'datasets_list'},
                'result': 'JupyterHub opens with the dataset in your "datasets" folder, and the dataset is '
                          'listed on your project page.',
            },
            {
                'title': 'Track your runs in MLflow',
                'body': [
                    'In your notebook, set your project\'s experiment and log the parameters and metrics of '
                    'your training with the usual MLflow commands. No login or token is needed: the workspace '
                    'is already connected to MLflow.',
                    'The experiment\'s name is shown in the Experiments table of your project. You can also '
                    'log artifacts, such as a table of metrics, and the trained model itself.',
                ],
                'code': (
                    'import mlflow\n'
                    'mlflow.set_experiment("<your experiment name>")\n'
                    '\n'
                    'with mlflow.start_run(run_name="first_run"):\n'
                    '    mlflow.log_param("model", "baseline")\n'
                    '    mlflow.log_metric("rmse", 0.42)'
                ),
            },
            {
                'title': 'See your results',
                'body': [
                    'In Projects, open your project and click the experiment\'s name. MLflow opens on that '
                    'experiment, with every run listed so that you can compare their parameters, metrics '
                    'and artifacts.',
                ],
                'link': {'label': 'My projects', 'url_name': 'projects_list'},
            },
            {
                'title': 'Register your model',
                'optional': True,
                'body': [
                    'If you logged the model, open the run in MLflow, click the model and choose '
                    '"Register model". Select "Create new model", give it a name and press "Register".',
                    'Each improved model you register under the same name becomes a new version, so you can '
                    'always trace which version came from which run.',
                ],
                'result': 'Version 1 of your model appears in MLflow.',
            },
        ],
    },
    {
        'slug': 'improve-with-public-data',
        'title': 'Improve your model with public data',
        'summary': 'Train the same model on a richer public dataset from the platform, compare the runs and '
                   'keep the better model as a new version.',
        'scenario': (
            "Alice's first model was trained on a small dataset of Alice's own. To get a more accurate "
            'model, Alice looks for more data on the platform.'
        ),
        'icon': 'fa-chart-line',
        'audience': 'AI developers and data scientists',
        'duration': 'About 20 minutes',
        'tools': 'Datasets, JupyterHub, MLflow',
        'steps': [
            {
                'title': 'Find a public dataset',
                'body': [
                    'In Datasets, open the "Public datasets" tab and filter by the energy domain of your '
                    'work.',
                    'Choose "Preview Data" on the dataset page to check that its columns match your own data.',
                    'If you have not trained a first model yet, start with '
                    '[Your first experiment](journey:first-experiment).',
                ],
                'link': {'label': 'Browse datasets', 'url_name': 'datasets_list'},
            },
            {
                'title': 'Add it to your project',
                'body': [
                    'On the dataset page, choose "Use in a Project", select the same project as your first '
                    'model and press Run.',
                ],
                'result': 'JupyterHub opens with the new dataset in your "datasets" folder, next to your own.',
            },
            {
                'title': 'Bring the data into the same format',
                'body': [
                    'If the columns or units differ from your own data, preprocess the new dataset in your '
                    'notebook so that your model can read it. The dataset page lists each column with its '
                    'unit and description.',
                ],
            },
            {
                'title': 'Train again in the same experiment',
                'body': [
                    'In your notebook, change the file path to the new dataset and keep the same experiment, '
                    'so that the two runs sit side by side. Give the new run its own name and run the training.',
                ],
                'code': (
                    'import mlflow\n'
                    'mlflow.set_experiment("<your experiment name>")\n'
                    '\n'
                    'with mlflow.start_run(run_name="with_public_data"):\n'
                    '    ...  # train and evaluate as before\n'
                    '    mlflow.log_metric("rmse", 0.38)'
                ),
            },
            {
                'title': 'Register the new model as a new version',
                'body': [
                    'In Projects, open your project and click the experiment\'s name. In MLflow, open the new '
                    'run, click its model and choose "Register model". Select the name you used for your first '
                    'model instead of creating a new one.',
                    'If you did not register your first model, register it too, under the same name.',
                ],
                'link': {'label': 'My projects', 'url_name': 'projects_list'},
                'result': 'The model becomes version 2 of the same registered model, linked to the run it '
                          'came from.',
            },
            {
                'title': 'Compare the versions',
                'body': [
                    'With both versions registered, compare them in MLflow to see their parameters and '
                    'metrics side by side.',
                ],
                'result': 'You see whether the richer data improved your model.',
            },
        ],
    },
    {
        'slug': 'contribute-dataset',
        'title': 'Contribute a dataset',
        'summary': 'Upload a dataset, describe it and publish it so that others on the platform can use it.',
        'scenario': (
            'Marta works at a pilot site that collects energy measurements and wants other '
            'researchers on the platform to be able to use the data.'
        ),
        'icon': 'fa-database',
        'audience': 'Data publishers, such as research groups and energy companies',
        'duration': 'About 10 minutes, plus the review',
        'tools': 'Datasets',
        'steps': [
            {
                'title': 'Start the upload',
                'body': [
                    'In Datasets, choose "Add new dataset". The upload has three parts: General, Upload and '
                    'Metadata.',
                ],
                'link': {'label': 'Add new dataset', 'url_name': 'dataset_upload'},
            },
            {
                'title': 'Describe the dataset',
                'body': [
                    'Give it a name, a description and the label of its energy domain',
                    'Tick "Do you want this dataset to be publicly available?" to submit it for publication. '
                    'Leave it unticked to keep the dataset private to you.',
                ],
            },
            {
                'title': 'Upload the file',
                'body': [
                    'Upload a .csv file, or a .zip archive with several files, of up to 500 MB. Keep the tab '
                    'open until the upload finishes.',
                ],
                'result': 'You receive an email when the upload is complete.',
            },
            {
                'title': 'Add metadata',
                'body': [
                    'Describe each column of your data with its unit and a short description, so that others '
                    'can understand it. Metadata is required, and you can provide it in one of two ways:',
                    'Upload a .json file in the format below, or insert it manually: choose "+ Add row" and '
                    'fill in the feature name, unit and description of each column. Use one of the two, not both.',
                ],
                'code': (
                    '{\n'
                    '  "temperature": ["°C", "Ambient temperature"],\n'
                    '  "humidity": ["%", "Relative humidity"]\n'
                    '}'
                ),
            },
            {
                'title': 'Wait for the review',
                'body': [
                    'A public dataset is checked by a reviewer before it appears in the public catalogue. Until '
                    'then its page shows "Awaiting review".',
                    'If it is rejected, its page shows the reason. A rejected dataset stays out of the public '
                    'catalogue, and editing it does not send it for review again: upload a corrected version '
                    'as a new dataset.',
                ],
                'result': 'You are notified of the decision. Once approved, the dataset is listed in Public '
                          'datasets for everyone.',
                'link': {'label': 'Datasets', 'url_name': 'datasets_list'},
            },
        ],
    },
    {
        'slug': 'pilot-twin-scenario',
        'title': 'Run a scenario on a pilot digital twin',
        'summary': 'Pick one of the pilot digital twins, run a scenario on it and take the result into a notebook.',
        'scenario': (
            'Rui works for a grid operator and wants to see how the network behaves in a new scenario '
            'before trying it on the real system.'
        ),
        'icon': 'fa-diagram-project',
        'audience': 'Engineers, analysts, researchers and decision-makers',
        'duration': 'About 15 minutes',
        'tools': 'Digital Twins, JupyterHub',
        'steps': [
            {
                'title': 'Pick a digital twin',
                'body': [
                    'DTs & Facilities lists the pilot sites of EnergyGuard. You can run scenarios on the '
                    'Transmission Grid (RDN), the CIEMAT Microgrid and the Antrodoco energy community, and '
                    'request experiments at the PEM Electrolyzer facility (BER).',
                ],
                'link': {'label': 'DTs & Facilities', 'url_name': 'digitaltwins-list'},
            },
            {
                'title': 'Choose a service',
                'body': [
                    'On the twin\'s page, "What can you do here?" lists the services you can use, for example '
                    'Grid Simulation, Renewable Generation Forecasting or the Smart Energy Optimiser, and the '
                    'twin\'s pilot data under "Datasets".',
                ],
            },
            {
                'title': 'Configure the scenario',
                'body': [
                    'Fill in the inputs the service asks for: a plant or a location, the time range, the assets '
                    'or the use case to simulate. Each service page explains what it needs.',
                ],
            },
            {
                'title': 'Run it',
                'body': [
                    'Choose "Run simulation" or "Run forecast". Most services answer within seconds. A grid '
                    'simulation on the RDN twin can take longer: you can leave the page and come back to it.',
                    'At the PEM Electrolyzer facility, choose "Submit Experiment Request" instead. The BER '
                    'laboratory runs the experiment and you are notified when the result is ready.',
                ],
                'result': 'The results appear on the page as charts and figures.',
            },
            {
                'title': 'Find your earlier runs',
                'body': [
                    'Every service keeps your runs: open "My runs", "View runs" or, at BER, "View requests" '
                    'on the service page to reopen a result or delete one you no longer need.',
                ],
            },
            {
                'title': 'Analyse the result in JupyterHub',
                'body': [
                    'On a result, choose "Save and Open in JupyterHub" (or "Open in JupyterHub") to copy it '
                    'into your JupyterHub folder.',
                ],
                'result': 'JupyterHub opens in a new tab with the result in your folder.',
            },
        ],
    },
    {
        'slug': 'assess-project',
        'title': 'Assess a project for trustworthiness',
        'summary': 'Run the EU AI Act questionnaire, a code analysis and a robustness test on one of your projects.',
        'scenario': (
            'Kate is responsible for compliance in a team that builds an AI service for grid '
            'operators. Before release, Kate needs to check the service against the EU AI Act and '
            'test its code and model.'
        ),
        'icon': 'fa-shield-halved',
        'audience': 'Providers and deployers of AI systems',
        'duration': 'About 45 minutes',
        'tools': 'AI Act questionnaire, Code analysis, Adversarial robustness',
        'steps': [
            {
                'title': 'Open Trustworthiness Assessments',
                'body': [
                    'Each assessment is attached to a project. You can assess the projects you and '
                    'your team created.',
                ],
                'link': {'label': 'Trustworthiness Assessments', 'url_name': 'trustworthiness:trustworthiness'},
            },
            {
                'title': 'Complete the EU AI Act questionnaire',
                'body': [
                    'On the "AI Act Questionnaire" card choose "Start Assessment", select your project and '
                    'start. Answer the questions about your AI system and your role.',
                    'Your answers are kept in your browser session: finish the questionnaire before you log out.',
                ],
                'result': 'You see your role, the risk category of your AI system and the obligations that '
                          'apply. The assessment is saved on your project.',
            },
            {
                'title': 'Analyse your code',
                'body': [
                    'On the "Code Analysis" card choose "Start Assessment" and select your project. Then '
                    'choose "GitHub Repository" and enter the repository URL or choose "Upload ZIP File".',
                ],
                'result': 'The scan runs in the background and its findings appear when it finishes.',
            },
            {
                'title': 'Test robustness against adversarial attacks',
                'body': [
                    'On the "Adversarial Robustness" card choose "Start Assessment" and select your project. '
                    'Upload a YAML configuration that points to your model in MLflow and lists the attacks '
                    'to run. Use "Download example config.yaml" on that page as a starting point.',
                    'This test needs a model logged in MLflow, so it applies to AI model projects.',
                ],
                'result': 'When the test finishes you see a report of how much each attack degrades your model.',
            },
            {
                'title': 'Review the results',
                'body': [
                    'The Results tab of Trustworthiness Assessments lists every assessment of your projects '
                    'with its status and a summary of the findings.',
                ],
                'link': {'label': 'Trustworthiness Assessments', 'url_name': 'trustworthiness:trustworthiness'},
            },
        ],
    },
]

JOURNEYS_BY_SLUG = {journey['slug']: journey for journey in JOURNEYS}


def _validate_journeys(journeys):
    slugs = set()
    for journey in journeys:
        slug = journey.get('slug')
        if not slug or slug in slugs:
            raise ImproperlyConfigured(f"JOURNEYS has a missing or duplicate slug: {slug!r}")
        slugs.add(slug)
        if not journey.get('steps'):
            raise ImproperlyConfigured(f"JOURNEYS['{slug}'] has no steps")


_validate_journeys(JOURNEYS)


INLINE_LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')


def _inline_url(target):
    if target.startswith('journey:'):
        slug = target.split(':', 1)[1]
        if slug not in JOURNEYS_BY_SLUG:
            raise NoReverseMatch(f'unknown journey {slug!r}')
        return reverse('journey_detail', args=[slug])
    return reverse(target)


def _render_paragraph(text):
    """A body paragraph as HTML: escaped text, with its [text](target) links resolved.
    A link whose target does not resolve is shown as plain text (and logged)."""
    parts, position = [], 0
    for match in INLINE_LINK.finditer(text):
        parts.append(escape(text[position:match.start()]))
        label, target = match.groups()
        try:
            parts.append(format_html('<a href="{}">{}</a>', _inline_url(target), label))
        except NoReverseMatch:
            logger.exception("Journey text links to an unknown target %r", target)
            parts.append(escape(label))
        position = match.end()
    parts.append(escape(text[position:]))
    return mark_safe(''.join(parts))


def _with_links(steps):
    """Steps with their link URLs resolved and their paragraphs rendered. A link whose
    URL name does not resolve is left out (and logged) rather than breaking the page."""
    resolved = []
    for step in steps:
        step = dict(step)
        step['body'] = [_render_paragraph(paragraph) for paragraph in step.get('body', [])]
        link = step.get('link')
        if link:
            try:
                step['link'] = {**link, 'url': reverse(link['url_name'], kwargs=link.get('kwargs'))}
            except NoReverseMatch:
                logger.exception("Journey step %r links to an unknown URL name %r", step['title'], link['url_name'])
                step['link'] = None
        resolved.append(step)
    return resolved


def _next_journey(slug):
    """The journey after `slug` in JOURNEYS, or None for the last one."""
    slugs = [journey['slug'] for journey in JOURNEYS]
    position = slugs.index(slug)
    return JOURNEYS[position + 1] if position + 1 < len(JOURNEYS) else None


@login_required
def journeys(request):
    return render(request, 'core/journeys.html', {
        'show_sidebar': True,
        'active_navbar_page': 'documentation',
        'journeys': JOURNEYS,
    })


@login_required
def journey_detail(request, slug):
    journey = JOURNEYS_BY_SLUG.get(slug)
    if journey is None:
        raise Http404
    return render(request, 'core/journey-detail.html', {
        'show_sidebar': True,
        'active_navbar_page': 'documentation',
        'journey': journey,
        'steps': _with_links(journey['steps']),
        'next_journey': _next_journey(slug),
    })
