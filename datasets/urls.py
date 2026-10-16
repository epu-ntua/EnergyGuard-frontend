from django.urls import path
from .views import AddDatasetView, dataset_approve, dataset_delete, dataset_details, dataset_download, dataset_edit, dataset_preview, dataset_reject, dataset_review_list, dataset_run, dataset_upload_success, datasets_list, generate_upload_url, DatasetsListJson, DATASET_FORMS

urlpatterns = [
    path('', datasets_list, name='datasets_list'),
    path('data/', DatasetsListJson.as_view(), name='datasets_list_json'),
    path('dataset/<int:dataset_id>/', dataset_details, name='dataset_details'),
    path('dataset/<int:dataset_id>/preview/', dataset_preview, name='dataset_preview'),
    path('dataset/<int:dataset_id>/download/', dataset_download, name='dataset_download'),
    path('dataset/<int:dataset_id>/run/', dataset_run, name='dataset_run'),
    path('dataset/<int:dataset_id>/edit/', dataset_edit, name='dataset_edit'),
    path('dataset/<int:dataset_id>/delete/', dataset_delete, name='dataset_delete'),
    path('dataset/<int:dataset_id>/approve/', dataset_approve, name='dataset_approve'),
    path('dataset/<int:dataset_id>/reject/', dataset_reject, name='dataset_reject'),
    path('review/', dataset_review_list, name='dataset_review_list'),
    path('dataset-upload/', AddDatasetView.as_view(DATASET_FORMS), name='dataset_upload'),
    path('dataset-upload-success/', dataset_upload_success, name='dataset-upload-success'),
    path('upload-url/', generate_upload_url, name='dataset-upload-url'),
]
