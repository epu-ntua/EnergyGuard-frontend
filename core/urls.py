from django.urls import path
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('home/', views.home, name='home'),
    path('collaboration-hub/', views.collaboration_hub, name='collaboration_hub'),
    path('documentation/', views.documentation, name='documentation'),
    path('error-not-exist/<str:error>/', views.error_does_not_exist, name='error_does_not_exist'),
]