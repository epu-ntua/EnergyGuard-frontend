from django.urls import path
from accounts import views

urlpatterns = [
    path('register/', views.RegistrationWizard.as_view(views.FORMS), name='register'),
    path('registration-success/', views.registration_success, name='registration_success'),
    path('login/', views.login_view, name='login'),
    path('profile/', views.profile, name='profile'),
]