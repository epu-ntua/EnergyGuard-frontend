from django.shortcuts import render

def tripetto_survey(request):
    return render(request, 'questionnaire/survey.html')