from django.urls import path
from . import views

urlpatterns = [
    path('home/', views.home, name='home'),
    path('experiments-list/', views.experiments_list, name='experiments_list'),

]
