"""
Runtime engine for the EU AI Act questionnaire.

questionnaire.json is the single source of truth for all question/step/item
content. This module only loads it and provides navigation/classification
helpers on top of it - it never hardcodes question text, links or answers.
"""
import json
import os
import re
from functools import lru_cache

JSON_PATH = os.path.join(os.path.dirname(__file__), 'questionnaire.json')

TRACK_NAMES = ('ai_system', 'gpai_model')

# Risk categories that end a track immediately, with no obligations checklist.
TERMINAL_RISK_CATEGORIES = {'prohibited', 'excluded', 'out_of_scope'}

_STEP_LABEL_NUM_RE = re.compile(r'^Step\s+([0-9A-Za-z.]+)', re.IGNORECASE)


@lru_cache(maxsize=1)
def load_data():
    with open(JSON_PATH, encoding='utf-8') as f:
        return json.load(f)


def get_metadata():
    return load_data()['metadata']


def get_roles():
    return load_data()['roles']


def get_risk_categories():
    return load_data()['risk_categories']


def get_track(track_name):
    return load_data()['tracks'][track_name]


def get_track_label(track_name):
    return get_track(track_name).get('label', track_name)


def get_steps(track_name):
    return get_track(track_name)['steps']


def get_obligations_mapping(track_name):
    return load_data()['obligations_mapping'][track_name]


@lru_cache(maxsize=None)
def _steps_index(track_name):
    steps = get_steps(track_name)
    by_id = {s['step_id']: s for s in steps}
    order = [s['step_id'] for s in steps]
    return by_id, order


def get_step(track_name, step_id):
    by_id, _ = _steps_index(track_name)
    return by_id.get(step_id)


def first_step_id(track_name):
    _, order = _steps_index(track_name)
    return order[0]


def _step_order_index(track_name, step_id):
    _, order = _steps_index(track_name)
    return order.index(step_id) if step_id in order else -1


def step_position(track_name, step_id):
    """1-indexed position of step_id within the track's declared step order,
    for a "Step X of Y" progress indicator."""
    index = _step_order_index(track_name, step_id)
    return index + 1 if index >= 0 else None


def _label_number(step):
    m = _STEP_LABEL_NUM_RE.match(step.get('step_label', ''))
    return m.group(1) if m else None


def resolve_hint_step_id(track_name, current_step_id, hint_text):
    """
    Resolve a derived_hints.goes_to_step_hint (e.g. "Step 4.3") to a concrete
    step_id in the track. Several steps can share the same leading number
    (e.g. "Step 4" for both GP-4a and GP-4b), so ties are broken by picking
    the earliest matching step *after* the current one in track order. A
    hint that only matches the current step itself (e.g. AI-1.1 "NOT SURE"
    -> "Step 1.1") is an explicit self-loop, not a dead end.
    """
    if not hint_text:
        return None
    m = _STEP_LABEL_NUM_RE.match(hint_text.strip())
    if not m:
        return None
    number = m.group(1)
    by_id, order = _steps_index(track_name)
    current_index = _step_order_index(track_name, current_step_id)

    candidates = [sid for sid in order if _label_number(by_id[sid]) == number]
    if not candidates:
        return None

    forward = [sid for sid in candidates if order.index(sid) > current_index]
    if forward:
        return min(forward, key=order.index)
    if current_step_id in candidates:
        return current_step_id
    return min(candidates, key=order.index)


def applicable_checklist_steps(track_name, risk_category, role):
    """
    Ordered, deduped list of checklist step_ids that apply for this
    risk_category/role, per obligations_mapping. role may be 'provider',
    'deployer', 'both', or None (no role identified -> no obligations).
    """
    if not risk_category or risk_category in TERMINAL_RISK_CATEGORIES:
        return []
    mapping = get_obligations_mapping(track_name)
    bucket = mapping.get(risk_category, {})
    roles_to_check = ('provider', 'deployer') if role == 'both' else ((role,) if role else ())

    ids = []
    for r in roles_to_check:
        for sid in bucket.get(r, []):
            if sid not in ids:
                ids.append(sid)

    _, order = _steps_index(track_name)
    ids.sort(key=lambda sid: order.index(sid) if sid in order else len(order))
    return ids


def always_steps(track_name):
    mapping = get_obligations_mapping(track_name)
    return list(mapping.get('always', {}).get('both', []))


def resolve_next(track_name, current_step_id, derived_hints, risk_category):
    """
    Pure hint-based navigation from a branching step: resolves
    derived_hints.goes_to_step_hint to a concrete step_id, or None if the
    track ends here (terminal risk category, or no hint at all).
    """
    if risk_category in TERMINAL_RISK_CATEGORIES:
        return None
    hint = (derived_hints or {}).get('goes_to_step_hint')
    return resolve_hint_step_id(track_name, current_step_id, hint) if hint else None


def build_landing_queue(track_name, landing_step_id, risk_category, role):
    """
    Given we are about to land on landing_step_id, expand it into the full
    ordered queue of steps to actually walk through. A plain (non-checklist)
    landing is just itself. A checklist landing is expanded using
    obligations_mapping once risk_category is known, since the source text
    sometimes names only one of several role-dependent checklists (e.g.
    "Step 5 (Provider) and/or Step 6 (Deployer)") while obligations_mapping
    is authoritative for which checklist step(s) actually apply. The
    track's "always" steps (e.g. AI literacy) are appended at the end.
    """
    landing_step = get_step(track_name, landing_step_id)
    if not landing_step or landing_step['type'] != 'checklist':
        return [landing_step_id]

    base = applicable_checklist_steps(track_name, risk_category, role) if risk_category else [landing_step_id]

    queue = list(base)
    for step_id in always_steps(track_name):
        if step_id not in queue:
            queue.append(step_id)
    return queue


def gpai_risk_classification(step_id, answer_value):
    """
    The gpai_model track's systemic-risk classification (standard vs
    systemic_risk) is decided at GP-1.3a/GP-1.3b by the chosen answer value
    itself rather than by a derived_hints.risk_category field.
    """
    value = (answer_value or '').strip().upper()
    if step_id == 'GP-1.3a' and value == 'YES':
        return 'systemic_risk'
    if step_id == 'GP-1.3b':
        return 'systemic_risk' if value == 'YES' else 'standard'
    return None


def compute_obligations(track_name, risk_category, role, checklist_status):
    """
    Build the results-screen obligations summary for one track: which
    checklist steps apply (per obligations_mapping) and, for each, which
    items are fulfilled vs outstanding based on the user's recorded status.
    """
    if not risk_category or risk_category in TERMINAL_RISK_CATEGORIES:
        return []

    always = always_steps(track_name)
    step_ids = applicable_checklist_steps(track_name, risk_category, role) + [
        sid for sid in always
        if sid not in applicable_checklist_steps(track_name, risk_category, role)
    ]

    fulfilled_statuses = {'COMPLETE', 'NOT_APPLICABLE'}
    summary = []
    for step_id in step_ids:
        step = get_step(track_name, step_id)
        # "always" steps such as AI literacy (AI-8) are a branching
        # acknowledgement, not a checklist - shown separately, not here.
        if not step or step['type'] != 'checklist':
            continue
        items = step.get('items', [])
        if role and role != 'both':
            items = [it for it in items if it.get('applicable_role') in (None, role)]

        item_statuses = checklist_status.get(step_id, {})
        fulfilled, outstanding = [], []
        for item in items:
            status = item_statuses.get(item['item_id'], 'NOT_STARTED')
            (fulfilled if status in fulfilled_statuses else outstanding).append({
                'item_id': item['item_id'],
                'number': item.get('number'),
                'text': item['text'],
                'status': status,
            })

        summary.append({
            'step_id': step_id,
            'step_label': step['step_label'],
            'fulfilled': fulfilled,
            'outstanding': outstanding,
        })
    return summary
