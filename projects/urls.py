from django.urls import path
from .views import *

urlpatterns = [
    path('', project_index, name='project_index'),
    path('list/', projects_list, name='projects_list'),
    path('data/', ProjectsListJson.as_view(), name='projects_list_json'),
    path('project/<int:project_id>/', project_details, name='project_details'),
    path('project-creation/', AddProjectView.as_view(PROJECT_FORMS), name='project_creation'),
]
