"""Engreen routes, mounted under digitaltwins/antrodoco/engreen-antrodoco-dt/."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.engreen_antrodoco_dt, name='engreen-antrodoco-dt'),
    path('runs/<int:run_id>/', views.engreen_antrodoco_run, name='engreen-antrodoco-run'),
    path('simulate/', views.engreen_pv_simulate, name='engreen-pv-simulate'),
    path('stations/', views.engreen_stations_api, name='engreen-stations-api'),
]
