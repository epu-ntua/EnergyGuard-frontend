from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('home/', views.home, name='home'),
    path('experiments-list/', views.experiments_list, name='experiments_list'),
    path('experiments-list-tabs/', views.experiments_list_tabs, name='experiments_list_tabs'),
    path('experiment/<int:experiment_id>/', views.experiment_details, name='experiment_details'),
    path('datasets-list/', views.datasets_list, name='datasets_list'),
    path('billing/', views.billing, name='billing'), 
    path('register/', views.RegistrationWizard.as_view(views.FORMS), name='register'),
    path('registration-success/', views.registration_success, name='registration_success'),
    path('login/', views.login_view, name='login'),
    path('collaboration-hub/', views.collaboration_hub, name='collaboration_hub'),
    path('documentation/', views.documentation, name='documentation'),
    path('dataset/<int:dataset_id>/', views.dataset_details, name='dataset_details'),
    path('error-not-exist/<str:error>/', views.error_does_not_exist, name='error_does_not_exist'),
]