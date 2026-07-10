import re

from django import template

from .. import engine

register = template.Library()

_OF_THE_AI_ACT_RE = re.compile(r'\s*of(?: the)? AI Act\s*', re.IGNORECASE)
_PAR_RE = re.compile(r'\bpar\.\s*', re.IGNORECASE)

_GUIDELINE_BADGE_META = {
    'commission_guidelines': ('bg-primary', 'bi-bank2'),
    'draft_commission_guidelines': ('bg-primary bg-opacity-75', 'bi-bank'),
    'draft_guidelines': ('bg-info text-dark', 'bi-file-earmark-text'),
    'code_of_practice': ('bg-success', 'bi-clipboard-check'),
    'explanatory_notice_template': ('bg-warning text-dark', 'bi-file-earmark-ruled'),
    'incident_reporting_guidance': ('bg-danger', 'bi-exclamation-triangle'),
    'other_guidance': ('bg-secondary', 'bi-info-circle'),
}
_DEFAULT_BADGE = ('bg-secondary', 'bi-link-45deg')

_STATUS_BADGE_CLASS = {
    'COMPLETE': 'bg-success',
    'IN_PROGRESS': 'bg-warning text-dark',
    'NOT_APPLICABLE': 'bg-secondary',
    'NOT_STARTED': 'bg-light text-dark border',
}


@register.filter
def guideline_badge_class(guideline_type):
    return _GUIDELINE_BADGE_META.get(guideline_type, _DEFAULT_BADGE)[0]


@register.filter
def guideline_badge_icon(guideline_type):
    return _GUIDELINE_BADGE_META.get(guideline_type, _DEFAULT_BADGE)[1]


@register.filter
def humanize_label(value):
    return (value or '').replace('_', ' ').strip().title()


_RISK_CATEGORY_LABELS = {
    'minimal_risk': 'Minimal or No Risk',
}


@register.filter
def risk_category_label(value):
    """Most risk_category slugs read fine through humanize_label's generic
    underscore-to-title conversion; 'minimal_risk' needs its own wording
    ('Minimal or No Risk') to match how this outcome is actually described
    to users."""
    return _RISK_CATEGORY_LABELS.get(value, humanize_label(value))


@register.filter
def status_badge_class(status):
    return _STATUS_BADGE_CLASS.get(status, _STATUS_BADGE_CLASS['NOT_STARTED'])


@register.filter
def filter_by_role(items, role):
    """Checklist items tagged with applicable_role only apply to that role;
    untagged items apply to everyone. Used for steps that mix provider- and
    deployer-only items (e.g. AI-7 Transparency)."""
    if not items or not role:
        return items
    return [item for item in items if item.get('applicable_role') in (None, role)]


@register.filter
def filter_by_gp4a(items, gp4a_answer):
    """GP-4b's visible items depend on the GP-4a Code of Practice answer;
    see engine.filter_gp4b_items for the rule."""
    if not items:
        return items
    return engine.filter_gp4b_items(items, gp4a_answer)


@register.filter
def article_label(label):
    """article_links labels are sourced as e.g. 'Article 6 par. 3 of the AI
    Act' - the article buttons only need 'Article 6 paragraph 3', since the
    AI Act is implied by context."""
    text = _OF_THE_AI_ACT_RE.sub('', label or '')
    text = _PAR_RE.sub('paragraph ', text)
    return text.strip()


@register.filter
def dedupe_by_url(links):
    """Some steps repeat the same guidance document once per referenced
    section (e.g. one guideline_links entry per sub_item it backs), all
    pointing at the same url - collapse those to a single badge."""
    if not links:
        return links
    seen = set()
    deduped = []
    for link in links:
        if link['url'] not in seen:
            seen.add(link['url'])
            deduped.append(link)
    return deduped
