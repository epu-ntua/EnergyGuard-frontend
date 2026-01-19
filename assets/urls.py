from django.urls import path
from assets import views

urlpatterns = [
    path('', views.assets_list, name='assets_list'),
]