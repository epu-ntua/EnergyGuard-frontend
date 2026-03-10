from django.urls import path
from accounts import views

urlpatterns = [
    path('register/', views.RegistrationWizard.as_view(views.REGISTRATION_FORMS), name='register'),
    path('platform-registration-success/', views.platform_registration_success, name='platform_registration_success'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.keycloak_logout, name='account_logout'),
    path('profile/', views.profile, name='profile'),
    # path('keycloak-redirect/', views.keycloak_redirect, name='account_keycloak_redirect'),
    path('profile/update-picture/', views.update_profile_picture, name='update_profile_picture'),
    path('team-management/', views.team_management, name='team_management'),
    path('invite/accept/<uuid:token>/', views.accept_invite, name='accept_invite'),
    path('invite/decline/<uuid:token>/', views.decline_invite, name='decline_invite'),
    path('invite/<int:invite_id>/resend/', views.resend_invite, name='resend_invite'),
    path('invite/<int:invite_id>/cancel/', views.cancel_invite, name='cancel_invite'),
    path('invite/<int:invite_id>/delete/', views.delete_invite, name='delete_invite'),
    path('team/remove-member/<int:user_id>/', views.remove_member, name='remove_member'),
    path('notifications/<int:notification_id>/read/', views.read_notification, name='read_notification'),
    path('notifications/poll/', views.poll_notifications, name='poll_notifications'),
    path('team/members-partial/', views.team_members_partial, name='team_members_partial'),
    path('team/pending-invites-partial/', views.pending_invites_partial, name='pending_invites_partial'),
]