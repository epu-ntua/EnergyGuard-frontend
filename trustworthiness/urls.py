from django.urls import path

from . import views

app_name = 'trustworthiness'

urlpatterns = [
    path('', views.trustworthiness, name='trustworthiness'),
    path('<str:slug>/', views.benchmark_detail, name='benchmark_detail'),
]
