from django.urls import path

from . import views

app_name = 'trustworthiness'

urlpatterns = [
    path('', views.trustworthiness, name='trustworthiness'),
    path('<str:slug>/', views.assessment_detail, name='assessment_detail'),
]
