from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone

from .models import Assessment

ASSESSMENT_TEMPLATES = {
    'ai-act-questionnaire': 'ai_act/mockup1.html',
    'code-analysis': 'code_analysis/mockup1.html',
    'robustness': 'robustness/config_input.html',
}

STATUS_BADGES = {
    Assessment.Status.COMPLETED: '<span class="badge badge-phoenix badge-phoenix-success fs-10-5">Completed</span>',
    Assessment.Status.FAILED: '<span class="badge badge-phoenix badge-phoenix-danger fs-10-5">Failed</span>',
    Assessment.Status.RUNNING: '<span class="badge badge-phoenix badge-phoenix-warning fs-10-5">Running</span>',
}


def _code_analysis_findings_summary(results):
    incidents = (results or {}).get('taxonomy', {}).get('incidents', []) or []
    if not incidents:
        return 'No findings'
    errors = sum(1 for i in incidents if str(i.get('severity') or '').upper() in {'ERROR', 'CRITICAL', 'HIGH'})
    warnings = sum(1 for i in incidents if str(i.get('severity') or '').upper() in {'WARNING', 'MEDIUM', 'MAJOR'})
    info = sum(1 for i in incidents if str(i.get('severity') or '').upper() in {'INFO', 'LOW', 'MINOR'})

    parts = []
    if errors:
        parts.append(f"{errors} error{'' if errors == 1 else 's'}")
    if warnings:
        parts.append(f"{warnings} warning{'' if warnings == 1 else 's'}")
    if info:
        parts.append(f'{info} info')
    return ' + '.join(parts) if parts else 'No findings'


def _robustness_findings_summary(results):
    data = results or {}
    report_meta = data.get('report_meta', {}) or {}
    attack_setup = data.get('attack_setup', {}) or {}
    metrics_by_key = {
        m.get('key'): m
        for m in (data.get('performance_summary', {}) or {}).get('primary_metrics', []) or []
        if isinstance(m, dict)
    }

    attack_name = report_meta.get('attack_name') or 'attack'
    epsilon = attack_setup.get('epsilon')
    eps_suffix = f' (ε={epsilon})' if epsilon is not None else ''

    for increase_key, baseline_key in (('rmse_increase', 'clean_rmse'), ('mae_increase', 'mae'), ('mse_increase', 'clean_mse')):
        increase = metrics_by_key.get(increase_key)
        baseline = metrics_by_key.get(baseline_key)
        if not (increase and baseline):
            continue
        try:
            baseline_value = float(baseline.get('value'))
            pct = float(increase.get('value')) / baseline_value * 100 if baseline_value else None
        except (TypeError, ValueError):
            pct = None
        if pct is not None:
            # The metric's own label already embeds epsilon (e.g. "RMSE Increase (ε=0.05)").
            return f"{increase.get('label', increase_key)} +{pct:.1f}% under {attack_name}"

    for key in ('accuracy_drop', 'attack_success_rate'):
        metric = metrics_by_key.get(key)
        if metric and metric.get('value') is not None:
            return f"{metric.get('label', key)}: {metric.get('value')} under {attack_name}{eps_suffix}"

    return 'No degradation metrics available'


def _ai_act_findings_summary(results):
    return (results or {}).get('final_classification') or '-'


FINDINGS_SUMMARY_BUILDERS = {
    Assessment.AssessmentType.CODE_ANALYSIS: _code_analysis_findings_summary,
    Assessment.AssessmentType.ROBUSTNESS: _robustness_findings_summary,
    Assessment.AssessmentType.AI_ACT: _ai_act_findings_summary,
}


def _findings_summary(assessment):
    if assessment.status != Assessment.Status.COMPLETED:
        return '-'
    builder = FINDINGS_SUMMARY_BUILDERS.get(assessment.assessment_type)
    return builder(assessment.results) if builder else '-'


def _build_assessment_runs(project_ids):
    assessments = (
        Assessment.objects
        .filter(project_id__in=project_ids)
        .select_related('project')
        .order_by('-created_at')
    )
    return [
        {
            'id': a.id,
            'type_raw': a.assessment_type,
            'project': a.project.name,
            'assessment_type': a.get_assessment_type_display(),
            'status': STATUS_BADGES.get(a.status, a.status),
            'score': '-',
            'accessed_at': timezone.localtime(a.created_at).strftime('%b %d, %Y'),
            'findings_summary': _findings_summary(a),
        }
        for a in assessments
    ]


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
        'assessment_runs_data': _build_assessment_runs(project_ids),
    })


@login_required
def assessment_detail(request, slug):
    template = ASSESSMENT_TEMPLATES.get(slug)
    if template is None:
        raise Http404
    return render(request, template, {
        'show_sidebar': True,
        'active_navbar_page': 'trustworthiness',
        'project_id': request.GET.get('project_id', ''),
    })
