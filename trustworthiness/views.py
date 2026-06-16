from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render

from .models import Assessment

ASSESSMENT_TEMPLATES = {
    'ai-act-questionnaire': 'ai_act/mockup1.html',
    'code-analysis': 'code_analysis/mockup1.html',
    'altai-self-assessment': 'altai/mockup1.html',
    'robustness': 'robustness/config_input.html',
}


@login_required
def trustworthiness(request):
    from projects.models import Project

    projects = list(
        Project.objects
        .filter(Q(creator=request.user) | Q(collaborators=request.user))
        .distinct()
        .annotate(experiments_count=Count('experiments', distinct=True))
        .order_by('-updated_at')
    )

    project_ids = [p.id for p in projects]
    last_assessment_map = {}
    for a in Assessment.objects.filter(project_id__in=project_ids).order_by('-created_at'):
        if a.project_id not in last_assessment_map:
            last_assessment_map[a.project_id] = a.created_at

    projects_data = []
    for p in projects:
        last_a = last_assessment_map.get(p.id)
        projects_data.append({
            'id': p.id,
            'name': p.name,
            'project_type': p.project_type,
            'project_type_display': p.get_project_type_display(),
            'experiments_count': p.experiments_count,
            'updated_at': p.updated_at.isoformat(),
            'last_assessment': last_a.isoformat() if last_a else None,
        })

    return render(request, 'trustworthiness/trustworthiness.html', {
        'show_sidebar': True,
        'active_navbar_page': 'trustworthiness',
        'projects_data': projects_data,
    })


@login_required
def assessment_detail(request, slug):
    template = ASSESSMENT_TEMPLATES.get(slug)
    if template is None:
        raise Http404
    return render(request, template, {
        'show_sidebar': True,
        'active_navbar_page': 'trustworthiness',
    })
