from django.shortcuts import render

def home(request):
    return render(request, 'mysite/index.html', {})

def error_does_not_exist(request, error=None):
    return render(request, 'mysite/error-does-not-exist.html', {"error": error})

def collaboration_hub(request):
    return render(request, 'mysite/collaboration-hub.html', {"active_navbar_page": "collaboration_hub", "show_vertical_navbar": True})

def documentation(request):
    return render(request, 'mysite/documentation.html', {"active_navbar_page": "documentation", "show_vertical_navbar": True})
