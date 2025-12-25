from django.urls import path
from experiments import views

urlpatterns = [
    path('list/', views.experiments_list, name='experiments_list'),
    path('list-tabs/', views.experiments_list_tabs, name='experiments_list_tabs'),
    path('experiment/<int:experiment_id>/', views.experiment_details, name='experiment_details'),
]