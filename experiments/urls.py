from django.urls import path
from .views import *

urlpatterns = [
    path('', experiment_index, name='experiment_index'),
    path('list/', experiments_list, name='experiments_list'),
    path('data/', ExperimentsListJson.as_view(), name='experiments_list_json'),
    path('experiment/<int:experiment_id>/', experiment_details, name='experiment_details'),
]