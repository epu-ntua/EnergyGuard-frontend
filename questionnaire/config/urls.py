"""
URL configuration for the EU AI Act questionnaire (questionnaire.json engine).
Included from main/urls.py under the 'surveys/' prefix.
"""
from django.contrib import admin
from django.urls import path
from questionnaire import views

app_name = 'questionnaire'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.intro, name='intro'),
    path('restart/', views.restart, name='restart'),
    path('results/', views.results, name='results'),
    path('download-json/', views.download_assessment_json, name='download_json'),
    path('start/<str:track>/', views.start_track, name='start_track'),
    path('<str:track>/back/', views.back_step, name='back'),
    path('<str:track>/not-sure/', views.not_sure_notice, name='not_sure_notice'),
    path('<str:track>/consult-restart/', views.consult_restart_notice, name='consult_restart_notice'),
    path('<str:track>/no-role/', views.no_role_notice, name='no_role_notice'),
    path('<str:track>/<str:step_id>/', views.step_view, name='step'),
    path('<str:track>/<str:step_id>/submit-answer/', views.submit_branching, name='submit_branching'),
    path('<str:track>/<str:step_id>/submit-checklist/', views.submit_checklist, name='submit_checklist'),
]
