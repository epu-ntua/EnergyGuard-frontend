from django.urls import path
from accounts import views

urlpatterns = [
    path('register/', views.RegistrationWizard.as_view(views.REGISTRATION_FORMS), name='register'),
    path('registration-success/', views.registration_success, name='registration_success'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.keycloak_logout, name='account_logout'),
    path('profile/', views.profile, name='profile'),
    path('keycloak-redirect/', views.keycloak_redirect, name='account_keycloak_redirect'),
    path('platform-entry/', views.PlatformEntryView.as_view(views.ENTRY_FORMS), name='platform_entry'),
]