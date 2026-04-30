"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from questionnaire import views

app_name = 'questionnaire'

urlpatterns = [
    path('<int:questionnaire_id>/', views.start_questionnaire, name='start'),
    path('question/<str:question_id>/', views.question_detail, name='detail'),
    path('question/<str:question_id>/submit/', views.submit_answer, name='submit'),
    path('out-of-scope/', views.out_of_scope_view, name='out_of_scope'),
    path('assessment-completed/', views.assessment_completed_view, name='assessment_completed'),
    path('download-json/', views.download_assessment_json, name='download_json'),
]
