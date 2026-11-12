from django.urls import path
from django.views.generic import RedirectView
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('home/', views.home, name='home'),
    path('collaboration-hub/', views.collaboration_hub, name='collaboration_hub'),
    path('documentation/', views.documentation, name='documentation'),
    path('documentation/tutorials/', views.journeys, {'section': 'tutorials'}, name='tutorials'),
    path('documentation/tutorials/<slug:slug>/', views.journey_detail, {'section': 'tutorials'},
         name='tutorial_detail'),
    path('documentation/how-to-guides/', views.journeys, {'section': 'guides'}, name='how_to_guides'),
    path('documentation/how-to-guides/<slug:slug>/', views.journey_detail, {'section': 'guides'},
         name='how_to_guide_detail'),
    # The how-to guides were called "Getting Started"; keep old links working. Temporary
    # (302) redirects, so that browsers do not cache them if the path is used again.
    path('documentation/getting-started/', RedirectView.as_view(pattern_name='how_to_guides')),
    path('documentation/getting-started/<slug:slug>/', RedirectView.as_view(pattern_name='how_to_guide_detail')),
    path('contact-form/', views.contact_form, name='contact_form'),
    path('error-not-exist/<str:error>/', views.error_does_not_exist, name='error_does_not_exist'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('hpc/', views.hpc, name='hpc'),
    path('ai-models/', views.ai_models, name='ai_models'),
    path('ai-models/deeptsf/', views.deeptsf_detail, name='deeptsf_detail'),
    path('ai-models/tirex/', views.tirex_detail, name='tirex_detail'),
    path('ai-models/request-access/', views.request_ai_model_access, name='ai_model_request_access'),
]