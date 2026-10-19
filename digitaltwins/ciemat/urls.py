"""CIEMAT routes, mounted under digitaltwins/ciemat/ciemat-forecasting-dt/."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.ciemat_forecasting_dt, name='ciemat-forecasting-dt'),
    path('runs/<int:run_id>/', views.ciemat_microgrid_run, name='ciemat-microgrid-run'),
    path('forecast/', views.ciemat_forecast, name='ciemat-forecast'),
    path('compare-forecasts/', views.ciemat_compare_forecasts, name='ciemat-compare-forecasts'),
    path('calculate/', views.ciemat_calculate, name='ciemat-calculate'),
    path('compare/', views.ciemat_compare, name='ciemat-compare'),
]
