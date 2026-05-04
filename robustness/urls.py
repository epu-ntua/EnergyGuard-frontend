from django.urls import path
from . import views

app_name = "robustness"

urlpatterns = [
    path("config-input/", views.config_input_view, name="config_input"),
    path("processing/", views.processing_view, name="processing"),
    path("processing/status/", views.job_status_api, name="job_status"),
    path("results/<str:job_id>/", views.results_view, name="results"),
    path("results/<str:job_id>/json/", views.results_json_view, name="results_json"),
    path("results/<str:job_id>/download-csv/", views.list_adversarial_csvs_view, name="list_adversarial_csvs"),
    path("results/<str:job_id>/download-csv/<str:attack_key>/", views.download_adversarial_csv_view, name="download_adversarial_csv"),
]
