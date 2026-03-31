from django.urls import path
from .views import AddDatasetView, dataset_delete, dataset_details, dataset_edit, dataset_preview, dataset_upload_success, datasets_list, DatasetsListJson, DATASET_FORMS

urlpatterns = [
    path('', datasets_list, name='datasets_list'),
    path('data/', DatasetsListJson.as_view(), name='datasets_list_json'),
    path('dataset/<int:dataset_id>/', dataset_details, name='dataset_details'),
    path('dataset/<int:dataset_id>/preview/', dataset_preview, name='dataset_preview'),
    path('dataset/<int:dataset_id>/edit/', dataset_edit, name='dataset_edit'),
    path('dataset/<int:dataset_id>/delete/', dataset_delete, name='dataset_delete'),
    path('dataset-upload/', AddDatasetView.as_view(DATASET_FORMS), name='dataset_upload'),
    path('dataset-upload-success/', dataset_upload_success, name='dataset-upload-success'),
]
