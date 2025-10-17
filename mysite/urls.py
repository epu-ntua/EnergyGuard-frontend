from django.urls import path
from . import views

urlpatterns = [
    path('home/', views.home, name='home'),
    path('experiments-list/', views.experiments_list, name='experiments_list'),
    path('datasets-list/', views.datasets_list, name='datasets_list'),
    path('billing/', views.billing, name='billing'),  # New billing path
    # path('register/', views.register, name='register'),
    path('register/', views.RegistrationWizard.as_view(views.FORMS), name='register'),
    path('registration-success/', views.registration_success, name='registration_success')
]
