"""RDN routes, mounted under digitaltwins/rdn-grid/rdn-grid-dt/."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.rdn_grid_dt, name='rdn-grid-dt'),
    path('runs/', views.rdn_grid_runs, name='rdn-grid-runs'),
    path('runs/<int:rdn_request_id>/', views.rdn_grid_results, name='rdn-grid-results'),
    path('runs/<int:rdn_request_id>/delete/', views.rdn_grid_run_delete, name='rdn-grid-run-delete'),
    path('runs/<int:rdn_request_id>/result.json', views.rdn_grid_result_data, name='rdn-grid-result-data'),
    path('simulate/', views.rdn_grid_simulate, name='rdn-grid-simulate'),
    path('status/', views.rdn_grid_job_status, name='rdn-grid-job-status'),
    path('follow/', views.rdn_grid_follow_lookup, name='rdn-grid-follow'),
]
