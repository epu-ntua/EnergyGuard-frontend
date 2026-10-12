"""CIEMAT routes, mounted under digitaltwins/ciemat/ciemat-forecasting-dt/."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.ciemat_forecasting_dt, name='ciemat-forecasting-dt'),
    path('forecast/', views.ciemat_forecast, name='ciemat-forecast'),
    path('calculate/', views.ciemat_calculate, name='ciemat-calculate'),
    path('compare/', views.ciemat_compare, name='ciemat-compare'),
]
