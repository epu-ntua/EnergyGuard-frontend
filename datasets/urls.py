from django.urls import path
from datasets import views

urlpatterns = [
    path('list/', views.datasets_list, name='datasets_list'),
    path('dataset/<int:dataset_id>/', views.dataset_details, name='dataset_details'),
]