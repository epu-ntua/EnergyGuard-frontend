from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

BENCHMARK_TEMPLATES = {
    'ai-act-questionnaire': 'ai_act/mockup1.html',
    'code-analysis': 'code_analysis/mockup1.html',
    'altai-self-assessment': 'altai/mockup1.html',
}


@login_required
def trustworthiness(request):
    return render(request, 'core/trustworthiness.html', {
        'show_sidebar': True,
        'active_navbar_page': 'trustworthiness',
    })


@login_required
def benchmark_detail(request, slug):
    template = BENCHMARK_TEMPLATES.get(slug)
    if template is None:
        raise Http404
    return render(request, template, {
        'show_sidebar': True,
        'active_navbar_page': 'trustworthiness',
    })
