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
    'deployer', or None (no role identified -> no obligations).
    """
    if not risk_category or risk_category in TERMINAL_RISK_CATEGORIES:
        return []
    mapping = get_obligations_mapping(track_name)
    bucket = mapping.get(risk_category, {})
    ids = list(bucket.get(role, [])) if role else []

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
    if (
        risk_category == 'systemic_risk'
        and current_step_id in ('GP-2.1i', 'GP-2.1ii')
        and hint == 'Step 3'
    ):
        # Step 3's open-source exception explicitly excludes GPAI models
        # with systemic risk ("...AND is not a GPAI with systemic risk"), so
        # once systemic risk was confirmed at Step 1.3a/1.3b, becoming a
        # provider here skips straight to Step 4 (Code of Practice) instead
        # of the moot exceptions check.
        hint = 'Step 4'
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


def filter_gp4b_items(items, gp4a_answer):
    """
    GP-4b's item list depends on the GP-4a Code of Practice answer: a
    provider fully adhering to the Code only owes 4.4 (training data
    summary) and 4.5 (EU representative), since the Code itself already
    covers the rest. Any other answer (NO / IN PROGRESS) still needs the
    full obligations list demonstrated through other adequate means.
    """
    if (gp4a_answer or '').strip().upper().startswith('YES'):
        return [item for item in items if item.get('required_even_if_full_adherence')]
    return items


def filter_gp5_items(items, gp4a_answer):
    """
    GP-5's visible items also depend on the GP-4a Code of Practice answer:
    full adherence already covers the systemic-risk Code of Practice item
    (5.2), leaving only the FLOP-threshold notification (5.1) to confirm
    separately. Any other answer means the Code-of-Practice route (5.2)
    isn't being taken, so the remaining systemic-risk obligations (5.3-5.6)
    must be demonstrated individually instead.
    """
    if (gp4a_answer or '').strip().upper().startswith('YES'):
        return [item for item in items if item['item_id'] in ('GP-5.1', 'GP-5.2')]
    return [item for item in items if item['item_id'] != 'GP-5.2']


def ai42_next_step_hint(selected_labels):
    """
    Step 4.2 lets the user check any combination of its lettered high-risk
    categories (a)-(e). Categories a-d go through the Article 6(3)
    derogations check at Step 4.3; category e (Annex I product-safety
    components) isn't subject to those derogations, so if it's the only
    thing selected the track skips straight to Step 5.
    """
    labels = set(selected_labels or [])
    if labels & {'a', 'b', 'c', 'd'}:
        return 'Step 4.3'
    if 'e' in labels:
        return 'Step 5'
    return None


def ai42_combined_warning(track_name, current_step_id, answers):
    """
    Step 4.3's derogations check doesn't apply to the Annex I product-safety
    category (e) from Step 4.2. If the user selected e together with any of
    a-d there, surface that sub_item's own warning again while on Step 4.3.
    """
    if current_step_id != 'AI-4.3':
        return None
    step = get_step(track_name, 'AI-4.2')
    if not step:
        return None
    stored_answer = (answers or {}).get('AI-4.2')
    selected = set(stored_answer) if isinstance(stored_answer, list) else set()
    if 'e' not in selected or not (selected & {'a', 'b', 'c', 'd'}):
        return None
    sub_item_e = next((si for si in step.get('sub_items', []) if si['label'] == 'e'), None)
    return (sub_item_e or {}).get('combined_selection_warning')


def ai5_completion_outcome(track_name, item_statuses):
    """
    Step 5 (Provider Compliance) branches on how its own checklist was
    answered, per its completion_outcomes: marking every item NOT_APPLICABLE
    means the user isn't actually a Provider after all ("I am a Deployer, not
    a Provider"), so the track reroutes to Step 6 with its role corrected to
    'deployer'. Any other outcome keeps following the normal queue to Step 7,
    with a warning surfaced first if any item isn't yet COMPLETE (don't
    release to market until all items are done).

    Returns (warning_text_or_None, role_override_or_None).
    """
    step = get_step(track_name, 'AI-5')
    outcomes = {
        (o.get('condition_raw') or '').upper(): o.get('next_step_raw')
        for o in (step or {}).get('completion_outcomes') or []
    }
    statuses = list((item_statuses or {}).values())
    if not statuses:
        return None, None

    if all(s == 'NOT_APPLICABLE' for s in statuses):
        return None, 'deployer'

    if not all(s == 'COMPLETE' for s in statuses):
        warning = next((text for cond, text in outcomes.items() if cond.startswith('IN PROGRESS')), None)
        return warning, None

    return None, None


def ai23_resolve(current_role, hints):
    """
    Step 2.3 ("Becoming a Provider?") answering NO means "no additional
    Provider obligations apply here", not "no role was found at all". If
    Step 2.2 already established a Deployer role, that determination stands:
    the role isn't wiped to 'no_role_detected', and - since NO here doesn't
    carry its own goes_to_step_hint - the track is routed on to Step 3.1 ·
    Territorial Scope exactly as the Provider (YES) branch does, instead of
    terminating. That "no role detected" ending is only correct when no role
    was set going into 2.3 (i.e. 2.2 was also NO).

    Returns (effective_role, effective_hints).
    """
    sets_role = hints.get('sets_role')
    if sets_role == 'no_role_detected' and current_role == 'deployer':
        return current_role, dict(hints, goes_to_step_hint='Step 3.1')
    return sets_role, hints


def ai7_all_not_applicable(item_statuses):
    """
    Step 7's transparency items are each scenario-specific (chatbot
    disclosure, synthetic content labelling, emotion recognition disclosure,
    deepfake disclosure). If every item the user actually answered is
    NOT_APPLICABLE, none of Article 50's transparency triggers apply to
    their system, so the track is reclassified as minimal risk regardless of
    how it was classified going into this step.
    """
    statuses = list((item_statuses or {}).values())
    return bool(statuses) and all(s == 'NOT_APPLICABLE' for s in statuses)


def compute_obligations(track_name, risk_category, role, checklist_status, answers=None):
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
        if role:
            items = [it for it in items if it.get('applicable_role') in (None, role)]
        if step_id == 'GP-4b':
            items = filter_gp4b_items(items, (answers or {}).get('GP-4a'))
        if step_id == 'GP-5':
            items = filter_gp5_items(items, (answers or {}).get('GP-4a'))

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
