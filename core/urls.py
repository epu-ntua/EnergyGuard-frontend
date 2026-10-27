from django.urls import path
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('home/', views.home, name='home'),
    path('collaboration-hub/', views.collaboration_hub, name='collaboration_hub'),
    path('documentation/', views.documentation, name='documentation'),
    path('documentation/getting-started/', views.journeys, name='journeys'),
    path('documentation/getting-started/<slug:slug>/', views.journey_detail, name='journey_detail'),
    path('contact-form/', views.contact_form, name='contact_form'),
    path('error-not-exist/<str:error>/', views.error_does_not_exist, name='error_does_not_exist'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('hpc/', views.hpc, name='hpc'),
    path('ai-models/', views.ai_models, name='ai_models'),
    path('ai-models/deeptsf/', views.deeptsf_detail, name='deeptsf_detail'),
    path('ai-models/tirex/', views.tirex_detail, name='tirex_detail'),
    path('ai-models/request-access/', views.request_ai_model_access, name='ai_model_request_access'),
]