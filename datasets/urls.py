from django.urls import path
from .views import *

urlpatterns = [
    path('', datasets_list, name='datasets_list'),
    path('data/', DatasetsListJson.as_view(), name='datasets_list_json'),
    path('dataset/<int:dataset_id>/', dataset_details, name='dataset_details'),
    path('dataset/<int:dataset_id>/download/', dataset_details, name='dataset_download'),
    path('add-dataset/', AddDatasetView.as_view(DATASET_FORMS), name='add_dataset'),

]