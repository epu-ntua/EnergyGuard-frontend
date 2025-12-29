from django.urls import path
from .views import datasets_list, DatasetsListJson, dataset_details

urlpatterns = [
    path('', datasets_list, name='datasets_list'),
    path('data/', DatasetsListJson.as_view(), name='datasets_list_json'),
    path('dataset/<int:dataset_id>/', dataset_details, name='dataset_details'),
]