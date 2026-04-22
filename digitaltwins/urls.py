from django.urls import path
from . import views

urlpatterns = [
    path('', views.map_view, name='digitaltwins-map'),
    path('list/', views.digitaltwins_list, name='digitaltwins-list'),
    path('<slug:slug>/', views.digitaltwins_detail, name='digitaltwins-detail'),
]
