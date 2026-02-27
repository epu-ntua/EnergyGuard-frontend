from django.urls import path
from .views import (
    AddExperimentView,
    AddProjectView,
    EXPERIMENT_FORMS,
    PROJECT_FORMS,
    ProjectsListJson,
    delete_experiment,
    delete_project,
    eval_results,
    eval_results_all,
    experiments_list,
    project_creation_success,
    project_details,
    project_index,
    projects_list,
)

urlpatterns = [
    path('', project_index, name='project_index'),
    path('list/', projects_list, name='projects_list'),
    path('data/', ProjectsListJson.as_view(), name='projects_list_json'),
    path('project/<int:project_id>/', project_details, name='project_details'),
    path('project/<int:project_id>/delete/', delete_project, name='delete_project'),
    path('project/<int:project_id>/experiments/', experiments_list, name='experiments_list'),
    path(
        'project/<int:project_id>/experiments/add/',
        AddExperimentView.as_view(EXPERIMENT_FORMS),
        name='add_experiment',
    ),
    path(
        'project/<int:project_id>/experiments/<int:experiment_id>/delete/',
        delete_experiment,
        name='delete_experiment',
    ),
    path(
        'project/<int:project_id>/experiments/<int:experiment_id>/eval-results/',
        eval_results,
        name='eval_results',
    ),
    path(
        'project/<int:project_id>/experiments/eval-results/',
        eval_results_all,
        name='eval_results_all',
    ),
    path('project-creation/', AddProjectView.as_view(PROJECT_FORMS), name='project_creation'),
    path('project-creation/success/', project_creation_success, name='project_creation_success'),
]
