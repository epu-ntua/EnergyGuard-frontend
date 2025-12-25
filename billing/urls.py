from django.urls import path
from billing import views

urlpatterns = [
    path('overview/', views.billing, name='billing'), 
]