"""Guided journeys: tutorials and how-to guides in the documentation.

Documentation only: a journey lists the steps to follow and links to the pages where
each one is done. Nothing is tracked.

Each journey belongs to a `section` of SECTIONS: a tutorial is a complete walkthrough
on sample data for someone learning the platform, a how-to guide covers one task for
someone who already knows what they want to do.

A journey can open with a `scenario`: one or two sentences about a persona and what they
want to achieve. `icon` is its FontAwesome icon.

The order of JOURNEYS is the order of the cards, and each journey suggests the next one
of its own section as its next journey.

Each step has a title, a short `body` (one paragraph per item), `optional` when the
journey works without it, an optional `link` to
the page where the step is done (`url_name` and optional `kwargs`, reversed when the
page is shown), an optional `code` sample, optional `images` (screenshots: `src` under
static/, `alt` and a short `caption`), and an optional `result` saying what the user
sees afterwards.

A body paragraph can link inline: `[text](journey:<slug>)` links to another journey,
`[text](<url_name>)` to a page of the platform. The rest of the text is escaped.

Only the steps are numbered. Whatever is not a step of the flow goes in optional fields
outside the numbered list: `intro` (paragraphs above the steps), `limitations` (a list
shown above the steps under "Limitations"), `reference` (a code block of commands at a
glance, above the steps), `extras` (tasks with no fixed order, shown after the steps
under "More you can do", each with a title, a `body` and an optional `code`) and `notes`
(a list shown last, under "Good to know"). Their paragraphs link inline like the steps'
do; `reference` is code, so the template reads it from the journey as it is.

_validate_journeys checks the fields when the module is imported: an unknown field, a
paragraph field that is not a list of strings, or a link to an unknown journey stops
the start-up.
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
    # The quick start describes a tutorial dataset and notebook that do not exist yet.
    # Every "REVIEW(quick-start)" comment marks text to check against them once they do
    # (grep -n "REVIEW(quick-start)" core/views/journeys.py).
    {
        'slug': 'quick-start',
        'section': 'tutorials',
        'title': 'Quick start: your first forecasting model',
        'summary': 'Bring your own forecasting model, or start from an example notebook that is ready to '
                   'run, and take it through the platform: train it on a dataset, track and compare its '
                   'runs in MLflow, register the best one and test its robustness.',
        'scenario': (
            'Sam is new to the platform. Sam wants to see how a forecast of a building\'s energy use is '
            'trained, tracked and checked on EnergyGuard. Sam can bring a model of Sam\'s own or, without '
            'one, start from the example notebook that comes with the tutorial dataset.'
        ),
        'intro': [
            'The steps follow the example notebook. If you have your own model, follow the same steps '
            'with your own notebook: each step says what changes. Your notebook runs under the same '
            'limitations, listed below, and '
            '[Your own Python environments and kernels](journey:custom-kernels) explains how to add the '
            'libraries it needs.',
        ],
        'icon': 'fa-rocket',
        'audience': 'New users, AI developers and data scientists',
        # REVIEW(quick-start): estimate; time it once the notebook and the robustness test exist.
        'duration': 'About 1 to 1.5 hours',
        'tools': 'Datasets, Projects, JupyterHub, MLflow, Trustworthiness Assessments',
        # The server's limits are also given in the notes of 'custom-kernels': keep both in step
        # with the JupyterHub configuration.
        'limitations': [
            'Resources: your server has 3 GB of memory, 1 vCPU core and no GPU. If a notebook goes over '
            '3 GB, the kernel is stopped and everything in memory is lost, so you have to run the notebook '
            'again from the top.',
            'Neural networks (TiDE here, or N-HiTS and similar models if you add them) need the most memory '
            'and time. Train them on small data and for a few NN_EPOCHS.',
            'This is a testing environment: please do not run long trainings here. One epoch of training '
            'over a file that is too big can take tens of minutes.',
            'Large files at their own resolution (1 second or 1 minute) are the most demanding: use '
            'SERIES_IDS to pick a few sensors, or set RESAMPLE = "1h".',
            'For larger datasets, such as the pilot ones, restart the kernel before running the notebook to '
            'save memory.',
        ],
        'steps': [
            {
                'title': 'Create a project',
                'body': [
                    'In Projects, choose "Add new project", give it a name that starts with your name, '
                    'for example "sam smart building forecast", and choose the project type AI Model.',
                ],
                'link': {'label': 'Add new project', 'url_name': 'project_creation'},
                'result': 'A confirmation page appears. Choose "Open project": its Experiments table shows '
                          'the MLflow experiment created for it, named "<project name>-default".',
            },
            {
                'title': 'Open the tutorial dataset and load it into your project',
                'body': [
                    'In Assets, open Datasets and choose "SMART Building Energy Demand (Tutorial)" in the '
                    '"Public datasets" tab. It is a small CSV file with hourly readings from five homes.',
                    'Choose "Preview Data" to see the first rows, then read the Metadata Table. It describes '
                    'each time series present in the CSV along with its units.',
                    'Then choose "Load in Project", select your project and press Load. Because this is the '
                    'tutorial dataset, the example notebook smart_building_forecasting.ipynb is copied into '
                    'your workspace together with the data.',
                    'With your own model, you can load this dataset as well, or load your own or another '
                    'public dataset instead. Only the tutorial dataset comes with the example notebook: '
                    'any other dataset is loaded without one.',
                ],
                'link': {'label': 'Browse datasets', 'url_name': 'datasets_list'},
                'result': 'JupyterHub opens in a new tab, which can take up to about 15 seconds the first '
                          'time. The data is in your read-only "datasets" folder and, if you loaded the '
                          'tutorial dataset, the example notebook is in your "notebooks" folder. The dataset '
                          'is listed under "Datasets used" on your project page.',
            },
            {
                'title': 'Run a notebook that logs your models',
                'body': [
                    'Open smart_building_forecasting.ipynb and keep the EnergyGuard kernel. In its Settings '
                    'cell (section 1), set the name of your project\'s experiment, as shown in the Experiments table of '
                    'your project. Then choose "Run All Cells" in the Run menu. The notebook needs no GPU '
                    'and nothing to install, and it finishes in a few minutes.',
                    # REVIEW(quick-start): test split (last 10%) and the three models must match
                    # the notebook; the neural network is there because FGSM/PGD need gradients.
                    'It keeps the last 10% of the data for testing and trains three models on the '
                    'rest: a naive baseline that repeats the same hour of the previous day (24 steps '
                    'earlier), a linear regression and a small neural network. Each model is logged as a '
                    'run in your experiment, with its parameters, its metrics and the model itself.',
                    'Section 8 of the notebook has no code to run: it explains the results of the code '
                    'analysis in step 8 of this tutorial, which is optional.',
                    'With your own model, drag your notebook into the "notebooks" folder of the JupyterHub '
                    'file browser. In it, set your project\'s experiment with mlflow.set_experiment and log '
                    'each model you train as a separate run, with its metrics and the model itself '
                    '(mlflow.<flavor>.log_model). No login or token is needed. '
                    '[Your first experiment](journey:first-experiment) shows the MLflow commands.',
                    'JupyterHub admits a limited number of users at the same time. If you cannot get in, try again later.',
                ],
                'code':'EXPERIMENT_NAME = "<your experiment name>"',
                # REVIEW(quick-start): metrics the notebook prints and logs.
                'result': 'One run is logged per model: three with the example notebook, which also prints '
                          'the error (RMSE and MAE) of each model on the test data.',
            },
            {
                'title': 'Compare the runs',
                'body': [
                    'In Projects, open your project. The Performance Metrics section shows a card for each '
                    'metric your runs logged, with a chart of its value in every run, and lists the runs '
                    'as R1, R2, R3 and so on, in the order they were logged. If your project has more than one '
                    'experiment, choose yours in the list next to the heading.',
                    'Each metric card shows the value of the latest run, while its chart shows every run. '
                    'For error metrics such as RMSE and MAE, the best run is the lowest point of the chart.',
                    'Click a run in the list to highlight it on every chart and see its values on the '
                    'cards. Click it again to clear the selection.',
                    'To see the parameters of each run as well, click the experiment\'s name in the '
                    'Experiments table. The first time, MLflow asks you to log in again: choose "Login with '
                    'Keycloak". MLflow then opens on the experiment, where you can tick the runs and choose '
                    '"Compare".',
                ],
                'link': {'label': 'My projects', 'url_name': 'projects_list'},
                'result': 'You can tell which model has the lowest error and, with the example notebook, '
                          'whether it beats the naive baseline.',
            },
            {
                'title': 'Try your own variation',
                'body': [
                    'In the Settings cell of the notebook (section 1), change a setting of a model or the '
                    'features it uses, for example LAGS, NN_INPUT_LENGTH or NN_EPOCHS, as section 5 '
                    '"Try it yourself" suggests. Then run the Settings cell and step 4 again.',
                    'With your own model, change a setting of your model and run your notebook again in '
                    'the same experiment.',
                ],
                'result': 'New runs appear in the experiment, one per model: with the example notebook, '
                          'they have the same names as the earlier ones. Compare them with the earlier runs '
                          'to see whether your change helped.',
            },
            {
                'title': 'Register your best model',
                'optional': True,
                'body': [
                    'In the experiment, open the "Models" tab, click your best model and choose "Register '
                    'model", then "Create new model". Each improved model you register later under the same '
                    'name becomes a new version. [Register your model in MLflow](journey:register-model) '
                    'shows each step with screenshots.',
                ],
                'result': 'Version 1 of your model appears in MLflow, linked to the run it came from.',
            },
            {
                'title': 'Test the robustness of your model',
                'body': [
                    'The cell of section 6 of the notebook, "Prepare the robustness test", writes '
                    'config.yaml next to the notebook. It is a configuration that points to the neural '
                    'network\'s run in MLflow. Download it from the file browser of JupyterHub.',
                    'In Trustworthiness Assessments, choose "Start Assessment" on the "Adversarial '
                    'Robustness" card, select your project and upload config.yaml.',
                    # Kept general on purpose: which models the robustness service accepts is not
                    # confirmed yet. Add the requirements once the colleague who owns it confirms them.
                    'With your own model, write a config.yaml of your own, starting from "Download example '
                    'config.yaml" on the same page or from the one the example notebook writes. The '
                    'configuration points to your model and to a test set in MLflow, and names the feature '
                    'and target columns of the test set, the task type and the range of the input values. '
                    'The attacks it lists, FGSM and PGD, are computed from the gradients of the model.',
                ],
                'link': {'label': 'Trustworthiness Assessments', 'url_name': 'trustworthiness:trustworthiness'},
                'result': 'When the test finishes, the Robustness Report opens after the processing page '
                          'and shows how much the attacks degrade the forecasts of your model, one attack at '
                          'a time. "Download Report" saves the metrics as JSON, and a CSV per attack holds the '
                          'attacked windows and both forecasts. The "Results" tab of Trustworthiness '
                          'Assessments lists your past assessments.',
            },
            {
                'title': 'Analyse the code of your model',
                'optional': True,
                'body': [
                    # The notebook does not write the archive on purpose: users make it themselves.
                    # code_analysis_upload.zip is the name section 8 of the notebook uses.
                    'Code Analysis scans a ZIP file with your code. This step adds about 5 minutes.',
                    'Save the notebook (Ctrl+S). In the file browser of JupyterHub, right-click '
                    'smart_building_forecasting.ipynb and choose "Download". On your computer, put the '
                    'downloaded notebook in a ZIP file named code_analysis_upload.zip: on Windows and '
                    'macOS, right-click the file and choose the option that compresses it to a ZIP file, '
                    'then rename the result.',
                    'In Trustworthiness Assessments, choose "Start Assessment" on the "Code Analysis" '
                    'card and select your project. Choose "Upload ZIP File", select '
                    'code_analysis_upload.zip, give the analysis a name and press "Upload and Continue".',
                    'With your own model, put your code in a .zip or .tar.gz file of up to 500 MB, or '
                    'choose "GitHub Repository" and enter the URL of its repository.',
                ],
                'link': {'label': 'Trustworthiness Assessments', 'url_name': 'trustworthiness:trustworthiness'},
                'result': 'A processing page follows, usually for under a minute, then the Analysis Report '
                          'with its Overview and Details tabs. Section 8 of the notebook, "Look at the code '
                          'analysis results", explains how to read it. The "Results" tab of Trustworthiness '
                          'Assessments lists the analysis with your other assessments.',
            },
            {
                'title': 'Complete the AI Act Questionnaire',
                'optional': True,
                'body': [
                    'In Trustworthiness Assessments, choose "Start Assessment" on the "AI Act '
                    'Questionnaire" card, select your project and answer the questions about your AI '
                    'system and your role. [Assess a project for trustworthiness](journey:assess-project) '
                    'describes every assessment of that page.',
                    'This step adds about 5 to 30 minutes.',
                    'Your answers are kept in your browser session: finish the questionnaire before you '
                    'log out.',
                ],
                'link': {'label': 'Trustworthiness Assessments', 'url_name': 'trustworthiness:trustworthiness'},
                'result': 'You see your role, the risk category of your AI system and the obligations that '
                          'apply. The assessment is saved on your project.',
            },
            {
                'title': 'Try it on other data',
                'optional': True,
                'body': [
                    # The column names are fixed in the notebook's load_long (step 2), not settings:
                    # keep this text in step with it.
                    'Open another dataset, for example one of the pilot datasets, or '
                    '[contribute your own](journey:contribute-dataset), and load it into the same project. '
                    'Keep your own dataset under 500 MB, and mind the limitations at the top of this page.',
                    'In the file browser of JupyterHub, open the "datasets" folder. Each dataset loaded into '
                    'your project has a folder there, named after the dataset, and the files inside it keep '
                    'the names the data provider gave them, which can differ from the name of the dataset. '
                    'To get the path of a file, right-click it and choose "Copy Path".',
                    'With the example notebook, in its Settings cell (section 1), set DATA_FILE to that path with "../" '
                    'in front of it, because the notebook sits in the "notebooks" folder, and set UNIT to the '
                    'unit of the values. Leave SERIES_IDS at None to use every series in the file, or list a '
                    'few of them to save memory. Then run the notebook again.',
                    'The notebook reads files with one reading per row, in the columns datetime, values and '
                    'sensor_id (or timeseries_id), as in the tutorial and pilot datasets, and the time step '
                    'of the data must divide one day. Its settings have no column names to change. If the '
                    'new data has other columns, other units or another format, convert it first, as '
                    '[Improve your model with public data](journey:improve-with-public-data) describes.',
                ],
                'code': 'DATA_FILE = "../datasets/<dataset name>/<file name>.csv"',
                'link': {'label': 'Browse datasets', 'url_name': 'datasets_list'},
                'result': 'The same notebook runs on the new data, and its runs sit next to the earlier '
                          'ones in your experiment.',
            },
        ],
        'notes': [
            'If you wish to install new libraries, read '
            '[Your own Python environments and kernels](journey:custom-kernels) to create your own Python '
            'environment and use it as a kernel.',
        ],
    },
    {
        'slug': 'first-experiment',
        'section': 'guides',
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
                    'choose "Load in Project", select your project and press Load.',
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
                    'If you logged the model, register it in MLflow to keep it under a name of your choice. '
                    'In the experiment, open the "Models" tab, click the model and choose "Register model", '
                    'then "Create new model".',
                    'Each improved model you register later under the same name becomes a new version, so you '
                    'can compare the versions and always trace which one came from which run. The '
                    '[Register your model in MLflow](journey:register-model) journey walks through each '
                    'step with screenshots.',
                ],
                'result': 'Version 1 of your model appears in MLflow.',
            },
        ],
    },
    {
        'slug': 'improve-with-public-data',
        'section': 'guides',
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
                    'On the dataset page, choose "Load in Project", select the same project as your first '
                    'model and press Load.',
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
                'title': 'Register the new version and compare',
                'body': [
                    'If you did not register your first model, register it now. Then register the model of '
                    'the new run under the same name, so that it becomes version 2, and compare the two '
                    'versions in MLflow. '
                    '[Register your model in MLflow](journey:register-model) shows each step.',
                ],
                'result': 'You see the metrics of both versions side by side and whether the richer data '
                          'improved your model.',
            },
        ],
    },
    {
        'slug': 'register-model',
        'section': 'guides',
        'title': 'Register your model in MLflow',
        'summary': 'Register a model logged in MLflow, keep each improved model as a new version and compare '
                   'the versions.',
        'scenario': (
            'Alice has logged the models of several training runs in MLflow and wants to keep the best '
            'ones under one name, with a version for each improvement.'
        ),
        'icon': 'fa-code-branch',
        'audience': 'AI developers and data scientists',
        'duration': 'About 5 minutes',
        'tools': 'Projects, MLflow',
        'steps': [
            {
                'title': 'Open the model in MLflow',
                'body': [
                    'You need a model logged in MLflow from a training run, as in '
                    '[Your first experiment](journey:first-experiment).',
                    'In Projects, open your project and click the experiment\'s name. MLflow opens on the '
                    'experiment.',
                    'Choose "Models" in the experiment\'s menu on the left. The table lists every model logged '
                    'in the experiment, with the run it came from and its metrics and parameters. The '
                    '"Registered models" column shows which of them are already registered.',
                ],
                'link': {'label': 'My projects', 'url_name': 'projects_list'},
                'images': [
                    {
                        'src': 'assets/img/journeys/mlflow-experiment-models.png',
                        'alt': 'The Models tab of an MLflow experiment, listing three logged models with their '
                               'source run, registered models, metrics and parameters.',
                        'caption': 'The models logged in the experiment.',
                    },
                ],
            },
            {
                'title': 'Register it',
                'body': [
                    'Click the name of the model you want to keep. Its page shows the metrics, parameters '
                    'and run of the model. Choose "Register model" at the top right.',
                    'The first time, select "Create new model" in the window that opens, give the model a '
                    'name and press "Register". For each improved model after that, select the name you '
                    'already have instead of creating a new one, so that it is kept as a new version.',
                ],
                'images': [
                    {
                        'src': 'assets/img/journeys/mlflow-logged-model.png',
                        'alt': 'The page of a logged model in MLflow, marked "Not registered", with the '
                               '"Register model" button at the top right.',
                        'caption': 'A logged model that is not registered yet.',
                    },
                    {
                        'src': 'assets/img/journeys/mlflow-register-dialog.png',
                        'alt': 'The "Register model" window with an existing registered model selected.',
                        'caption': 'Registering the model under an existing name, as a new version.',
                    },
                ],
                'result': 'The model is registered as version 1 of a new name, or as the next version of an '
                          'existing one, linked to the run it came from.',
            },
            {
                'title': 'Find your registered model',
                'body': [
                    'Go to the MLflow home page, outside the experiment, by clicking the EnergyGuard logo at '
                    'the top left, and choose "Models" in the menu on the left.',
                    'This page lists every registered model with its latest version. Click the name of your '
                    'model.',
                ],
                'images': [
                    {
                        'src': 'assets/img/journeys/mlflow-registered-models.png',
                        'alt': 'The Registered Models page of MLflow, listing two models with their latest '
                               'version and last modified date.',
                        'caption': 'The registered models in MLflow.',
                    },
                ],
            },
            {
                'title': 'Compare the versions',
                'optional': True,
                'body': [
                    'The model page lists its versions with the date each was registered. Once there are two '
                    'or more, tick the versions you want to compare and press "Compare".',
                ],
                'images': [
                    {
                        'src': 'assets/img/journeys/mlflow-model-versions.png',
                        'alt': 'The page of a registered model in MLflow, with versions 1 and 2 ticked and the '
                               '"Compare" button next to the Versions heading.',
                        'caption': 'Selecting two versions to compare.',
                    },
                ],
                'result': 'You see the parameters and metrics of the versions side by side.',
            },
        ],
    },
    {
        'slug': 'contribute-dataset',
        'section': 'guides',
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
        'section': 'guides',
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
        'section': 'guides',
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
    {
        'slug': 'custom-kernels',
        'section': 'guides',
        'title': 'Your own Python environments and kernels',
        'summary': 'Create your own Python environment in JupyterHub, install the packages and versions you '
                   'need and use it as a kernel in your notebooks.',
        'scenario': (
            'Nikos needs a newer version of a forecasting library than the one in the EnergyGuard '
            'kernel, and wants to install it without losing the packages the platform already provides.'
        ),
        'icon': 'fa-cubes',
        'audience': 'AI developers and data scientists',
        'duration': 'About 10 minutes',
        'tools': 'JupyterHub',
        'intro': [
            'Every notebook runs in a kernel. The default kernel, EnergyGuard (Python), already has the '
            'EnergyGuard SDK, pandas, PyTorch, Darts, MLflow, scikit-learn and more. This kernel is '
            'read-only, so everyone gets the same, tested versions.',
            'If you need other packages or versions, you can create your own environment. Each environment '
            'you create appears as a new kernel. It is saved in your personal storage, so it is still there '
            'after your server stops and starts again.',
        ],
        'reference': (
            '# Create an environment with all EnergyGuard packages\n'
            'eg-new-kernel my-env\n'
            '\n'
            '# Create an empty environment\n'
            'eg-new-kernel my-env --clean\n'
            '\n'
            '# Add your own label in the launcher\n'
            'eg-new-kernel my-env --display-name "Forecasting"\n'
            '\n'
            '# Install a package (terminal)\n'
            '/home/jovyan/.local/envs/my-env/bin/pip install <package>\n'
            '\n'
            '# Install a package (notebook cell)\n'
            '!/home/jovyan/.local/envs/my-env/bin/pip install <package>\n'
            '\n'
            '# Add the EnergyGuard SDK to a clean environment\n'
            '/home/jovyan/.local/envs/my-env/bin/pip install /opt/energyguard-sdk/energyguard_sdk-*.whl mlflow==3.8.1\n'
            '\n'
            '# Activate it in a terminal\n'
            'source /home/jovyan/.local/envs/my-env/bin/activate\n'
            '\n'
            '# List kernels\n'
            'eg-new-kernel --list\n'
            '\n'
            '# Delete an environment and its kernel\n'
            'eg-new-kernel --remove my-env'
        ),
        'steps': [
            {
                'title': 'Create an environment',
                'body': [
                    'Open a terminal (File › New › Terminal) and run one of the commands below. Each comment '
                    'says what you get and how the kernel is shown in the launcher. Then reload the '
                    'JupyterLab page (F5).',
                    'The environment is stored in the folder /home/jovyan/.local/envs/my-env. The launcher '
                    'always shows this real name first. Names may contain letters, digits, ., _ and -. The '
                    'names eg-default and python3 are reserved.',
                    'Based on EnergyGuard (the default): your environment uses every EnergyGuard package '
                    'without copying it, so it takes almost no space. A package you install there replaces '
                    'the EnergyGuard version only in your environment.',
                    'With --clean: nothing from EnergyGuard is included, not even the SDK (see "Add the '
                    'EnergyGuard SDK to a clean environment" below). Everything you install uses your disk '
                    'space. PyTorch alone is several hundred MB.',
                ],
                'code': (
                    '# Everything EnergyGuard has, plus your own packages\n'
                    '# Shown as: my-env (EnergyGuard)\n'
                    'eg-new-kernel my-env\n'
                    '\n'
                    '# The same, with your own label\n'
                    '# Shown as: my-env (Forecasting)\n'
                    'eg-new-kernel my-env --display-name "Forecasting"\n'
                    '\n'
                    '# An empty environment (only Python and pip)\n'
                    '# Shown as: my-env\n'
                    'eg-new-kernel my-env --clean'
                ),
                'result': 'The kernel appears in the launcher and under Kernel › Change Kernel.',
            },
            {
                'title': 'Install packages',
                'body': [
                    'Always use the full path to the pip of your environment, unless you have activated the '
                    'environment and you are working in the terminal.',
                ],
                'code': (
                    '# In a notebook cell\n'
                    '!/home/jovyan/.local/envs/my-env/bin/pip install <package>\n'
                    '\n'
                    '# In a terminal\n'
                    '/home/jovyan/.local/envs/my-env/bin/pip install <package>'
                ),
            },
            {
                'title': 'Use it in a notebook',
                'body': [
                    'For a new notebook, pick your kernel in the launcher. For an existing notebook, choose '
                    'Kernel › Change Kernel… and then your kernel.',
                ],
            },
        ],
        'extras': [
            {
                'title': 'Use it in a terminal',
                'body': [
                    'Activating an environment affects only that terminal window. Notebooks always use the '
                    'kernel chosen in the notebook, and a new terminal starts without any environment active.',
                ],
                'code': (
                    'source /home/jovyan/.local/envs/my-env/bin/activate   # the prompt now starts with (my-env)\n'
                    'pip install <package>                                 # inside an activated environment, plain pip works\n'
                    'python my_script.py\n'
                    'deactivate                                            # back to normal'
                ),
            },
            {
                'title': 'List or remove environments',
                'body': [
                    'If a name is taken ("Environment already exists"), choose another one or remove the '
                    'old environment first.',
                ],
                'code': (
                    'eg-new-kernel --list            # all kernels you can use\n'
                    'eg-new-kernel --remove my-env   # delete the kernel and its environment'
                ),
            },
            # mlflow==3.8.1, here and in 'reference': keep in step with the MLflow version of the
            # EnergyGuard kernel image.
            {
                'title': 'Add the EnergyGuard SDK to a clean environment',
                'body': [
                    'The SDK is what logs you in to MLflow automatically, without tokens to copy. '
                    'Environments based on EnergyGuard already have it. In a --clean environment, install it '
                    'from the package that ships with the server, together with MLflow.',
                    'mlflow==3.8.1 is the same version as in the EnergyGuard kernel, so it matches the MLflow '
                    'server. Restart the kernel afterwards.',
                ],
                'code': (
                    '# In a terminal\n'
                    '/home/jovyan/.local/envs/my-env/bin/pip install /opt/energyguard-sdk/energyguard_sdk-*.whl mlflow==3.8.1\n'
                    '\n'
                    '# Or in a notebook cell\n'
                    '!/home/jovyan/.local/envs/my-env/bin/pip install /opt/energyguard-sdk/energyguard_sdk-*.whl mlflow==3.8.1'
                ),
            },
        ],
        # The server's limits are also given in the limitations of 'quick-start': keep both in
        # step with the JupyterHub configuration.
        'notes': [
            'Resources: your server has 3 GB of memory and 1 CPU core, and no GPU, whichever kernel you use. '
            'If a notebook goes over 3 GB, its kernel is stopped and you run the notebook again from the top.',
            'PyTorch in your own environment: put torch.set_num_threads(1) at the top of the notebook. '
            'Otherwise PyTorch starts one thread per core of the whole machine and runs many times slower on '
            'your single core.',
            'Kernels share memory: every open kernel counts towards your 3 GB. Shut down the ones you do not '
            'need (Kernel › Shut Down All Kernels).',
            'Kernel not in the launcher? Reload the page. If it is still missing, check eg-new-kernel --list.',
        ],
    },
]

JOURNEYS_BY_SLUG = {journey['slug']: journey for journey in JOURNEYS}

# The documentation sections journeys are listed in, in the order of their cards on the
# Documentation page: title, description and icon, and the URL names of their list and
# detail pages. The journeys of the last one of a section lead to the next section.
SECTIONS = {
    'tutorials': {
        'title': 'Tutorials',
        'description': 'Complete walkthroughs on sample data, from a dataset to a tracked and assessed model.',
        'icon': 'fa-graduation-cap',
        'list_url': 'tutorials',
        'detail_url': 'tutorial_detail',
    },
    'guides': {
        'title': 'How-to guides',
        'description': 'Step-by-step guides for common tasks. Each guide shows the steps to follow and where '
                       'to do them.',
        'icon': 'fa-bars-staggered',
        'list_url': 'how_to_guides',
        'detail_url': 'how_to_guide_detail',
    },
}

# The tutorial the dashboard suggests to users who do not know where to start.
QUICK_START_SLUG = 'quick-start'


INLINE_LINK = re.compile(r'\[([^\]]+)\]\(([^)\s]+)\)')

JOURNEY_FIELDS = {
    'slug', 'section', 'title', 'summary', 'scenario', 'icon', 'audience', 'duration', 'tools',
    'steps', 'intro', 'limitations', 'reference', 'extras', 'notes',
}
STEP_FIELDS = {'title', 'body', 'optional', 'link', 'code', 'images', 'result'}
EXTRA_FIELDS = {'title', 'body', 'code'}
# The fields that hold a list of paragraphs, rendered with their inline links
PARAGRAPH_FIELDS = ('intro', 'limitations', 'notes')


def _check_paragraphs(where, paragraphs):
    # A string here would be shown one character per paragraph
    if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
        raise ImproperlyConfigured(f"{where} must be a list of strings")


def _check_fields(where, item, allowed):
    unknown = set(item) - allowed
    if unknown:
        raise ImproperlyConfigured(f"{where} has unknown fields: {sorted(unknown)}")


def _paragraphs(journey):
    """Every paragraph of `journey` that can hold an inline link."""
    for step in journey['steps']:
        yield from step.get('body', [])
    for extra in journey.get('extras', []):
        yield from extra.get('body', [])
    for field in PARAGRAPH_FIELDS:
        yield from journey.get(field, [])


def _validate_journeys(journeys):
    slugs = set()
    for journey in journeys:
        slug = journey.get('slug')
        if not slug or slug in slugs:
            raise ImproperlyConfigured(f"JOURNEYS has a missing or duplicate slug: {slug!r}")
        slugs.add(slug)
        where = f"JOURNEYS['{slug}']"
        _check_fields(where, journey, JOURNEY_FIELDS)
        if journey.get('section') not in SECTIONS:
            raise ImproperlyConfigured(f"{where} has an unknown section: {journey.get('section')!r}")
        if not journey.get('steps'):
            raise ImproperlyConfigured(f"{where} has no steps")
        for step in journey['steps']:
            _check_fields(f"{where} step {step.get('title')!r}", step, STEP_FIELDS)
            _check_paragraphs(f"{where} step {step.get('title')!r} body", step.get('body', []))
        if not isinstance(journey.get('extras', []), list):
            raise ImproperlyConfigured(f"{where}['extras'] must be a list")
        for extra in journey.get('extras', []):
            _check_fields(f"{where} extra {extra.get('title')!r}", extra, EXTRA_FIELDS)
            if not extra.get('title'):
                raise ImproperlyConfigured(f"{where} has an extra with no title")
            _check_paragraphs(f"{where} extra {extra['title']!r} body", extra.get('body', []))
        for field in PARAGRAPH_FIELDS:
            _check_paragraphs(f"{where}['{field}']", journey.get(field, []))
        if not isinstance(journey.get('reference', ''), str):
            raise ImproperlyConfigured(f"{where}['reference'] must be a string")
    # Links to other journeys are checked here, once every slug is known, so that a typo
    # stops the start-up rather than leaving a plain-text "link" on the page. Links to
    # pages of the platform cannot be: the URLconf is not loaded yet (see core/tests.py).
    for journey in journeys:
        for paragraph in _paragraphs(journey):
            for _label, target in INLINE_LINK.findall(paragraph):
                if target.startswith('journey:') and target.split(':', 1)[1] not in slugs:
                    raise ImproperlyConfigured(
                        f"JOURNEYS['{journey['slug']}'] links to an unknown journey: {target!r}"
                    )
    quick_start = next((journey for journey in journeys if journey['slug'] == QUICK_START_SLUG), None)
    if quick_start is None or quick_start['section'] != 'tutorials':
        raise ImproperlyConfigured(f"QUICK_START_SLUG {QUICK_START_SLUG!r} is not a tutorial in JOURNEYS")


_validate_journeys(JOURNEYS)


def journey_url(journey):
    """The detail page of `journey`, under its own section."""
    return reverse(SECTIONS[journey['section']]['detail_url'], args=[journey['slug']])


def quick_start_url():
    return journey_url(JOURNEYS_BY_SLUG[QUICK_START_SLUG])


def sections():
    """The sections in the order of SECTIONS, each with its key."""
    return [{'key': key, **section} for key, section in SECTIONS.items()]


def _inline_url(target):
    if target.startswith('journey:'):
        slug = target.split(':', 1)[1]
        if slug not in JOURNEYS_BY_SLUG:
            raise NoReverseMatch(f'unknown journey {slug!r}')
        return journey_url(JOURNEYS_BY_SLUG[slug])
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


def _section_journeys(section):
    return [journey for journey in JOURNEYS if journey['section'] == section]


def _next_journey(journey):
    """The journey after `journey` in its own section, or None for the last one."""
    siblings = _section_journeys(journey['section'])
    position = [sibling['slug'] for sibling in siblings].index(journey['slug'])
    return siblings[position + 1] if position + 1 < len(siblings) else None


def _next_section(section):
    """The section after `section` in SECTIONS, or None for the last one."""
    keys = list(SECTIONS)
    position = keys.index(section)
    return SECTIONS[keys[position + 1]] if position + 1 < len(keys) else None


@login_required
def journeys(request, section):
    return render(request, 'core/journeys.html', {
        'show_sidebar': True,
        'active_navbar_page': 'documentation',
        'section': SECTIONS[section],
        'journeys': _section_journeys(section),
    })


@login_required
def journey_detail(request, slug, section):
    journey = JOURNEYS_BY_SLUG.get(slug)
    if journey is None or journey['section'] != section:
        raise Http404
    next_journey = _next_journey(journey)
    return render(request, 'core/journey-detail.html', {
        'show_sidebar': True,
        'active_navbar_page': 'documentation',
        'section': SECTIONS[section],
        'journey': journey,
        'intro': [_render_paragraph(paragraph) for paragraph in journey.get('intro', [])],
        'limitations': [_render_paragraph(paragraph) for paragraph in journey.get('limitations', [])],
        'steps': _with_links(journey['steps']),
        'extras': [
            {**extra, 'body': [_render_paragraph(paragraph) for paragraph in extra.get('body', [])]}
            for extra in journey.get('extras', [])
        ],
        'notes': [_render_paragraph(paragraph) for paragraph in journey.get('notes', [])],
        'next_journey': next_journey,
        # The last journey of a section leads on to the next section instead.
        'next_section': None if next_journey else _next_section(section),
    })
