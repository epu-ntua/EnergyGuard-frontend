from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def ai_models(request):
    return render(request, 'core/ai-models.html', {
        'show_sidebar': True,
        'active_navbar_page': 'ai_models',
    })
