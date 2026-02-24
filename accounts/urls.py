from django.urls import path
from accounts import views

urlpatterns = [
    path('register/', views.RegistrationWizard.as_view(views.REGISTRATION_FORMS), name='register'),
    path('platform-registration-success/', views.platform_registration_success, name='platform_registration_success'),
    path('registration-success/', views.keycloak_registration_success, name='keycloak_registration_success'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.keycloak_logout, name='account_logout'),
    path('profile/', views.profile, name='profile'),
    # path('keycloak-redirect/', views.keycloak_redirect, name='account_keycloak_redirect'),
    path('platform-entry/', views.PlatformEntryView.as_view(views.ENTRY_FORMS), name='platform_entry'),
    path('profile/update-picture/', views.update_profile_picture, name='update_profile_picture'),
    path('team-management/', views.team_management, name='team_management'),
]