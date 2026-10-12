"""REA Riga routes, mounted under digitaltwins/riga/rea-riga-dt/."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.rea_riga_dt, name='riga-map'),
    path('buildings/', views.rea_riga_buildings_api, name='rea-riga-buildings-api'),
]
