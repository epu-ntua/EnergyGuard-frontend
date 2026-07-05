from django.urls import path
from .views import (
    configure_github, configure_jupyter, configure_upload, edit_assessment, job_status_api,
    processing, results, results_json, select_source, view_assessment, view_assessment_results,
)

app_name = 'code_analysis'

urlpatterns = [
    path('', select_source, name='select_source'),
    path('configure/jupyter/', configure_jupyter, name='configure_jupyter'),
    path('configure/github/', configure_github, name='configure_github'),
    path('configure/upload/', configure_upload, name='configure_upload'),
    path('processing/', processing, name='processing'),
    path('processing/status/', job_status_api, name='job_status_api'),
    path('results/<str:job_id>/', results, name='results'),
    path('results/<str:job_id>/json/', results_json, name='results_json'),
    path('assessments/<int:assessment_id>/view/', view_assessment, name='view_assessment'),
    path('assessments/<int:assessment_id>/view/results/', view_assessment_results, name='view_assessment_results'),
    path('assessments/<int:assessment_id>/edit/', edit_assessment, name='edit_assessment'),
]