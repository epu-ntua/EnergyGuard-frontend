import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect

from . import engine
from .models import AIActAssessment

logger = logging.getLogger(__name__)

SESSION_KEY = 'ai_act'


def _empty_track_state():
    return {
        'started': False,
        'completed': False,
        'current_step': None,
        'queue': [],
        'history': [],
        'role': None,
        'risk_category': None,
        'answers': {},
        'checklist_status': {},
    }


def _push_history(track_state, step_id):
    if not track_state['history'] or track_state['history'][-1] != step_id:
        track_state['history'].append(step_id)


def _get_state(request):
    state = request.session.get(SESSION_KEY)
    if not state:
        state = {
            'tracks': {name: _empty_track_state() for name in engine.TRACK_NAMES},
            'active_track': None,
        }
        request.session[SESSION_KEY] = state
    return state


def _save_state(request, state):
    request.session[SESSION_KEY] = state
    request.session.modified = True


def _advance_track(track_state, track_name, landing_step_id):
    """Move the track onto landing_step_id, expanding checklist landings
    into their full queue (role-based checklists + always-steps)."""
    queue = engine.build_landing_queue(
        track_name, landing_step_id, track_state['risk_category'], track_state['role']
    )
    track_state['current_step'] = queue[0]
    track_state['queue'] = queue[1:]


def _finish_current_step(track_state):
    """After a queued step is answered with nowhere further to go, move to
    the next queued step, or mark the track complete."""
    if track_state['queue']:
        track_state['current_step'] = track_state['queue'].pop(0)
    else:
        track_state['completed'] = True
        track_state['current_step'] = None


def _combined_roles_list(state):
    return sorted({
        state['tracks'][name]['role'] for name in engine.TRACK_NAMES
        if state['tracks'][name]['role']
    })


def _persist_snapshot(request, state):
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    track_results = {
        name: {
            'risk_category': state['tracks'][name]['risk_category'],
            'role': state['tracks'][name]['role'],
            'completed': state['tracks'][name]['completed'],
        }
        for name in engine.TRACK_NAMES if state['tracks'][name]['started']
    }
    answers = {
        name: state['tracks'][name]['answers']
        for name in engine.TRACK_NAMES if state['tracks'][name]['started']
    }
    checklist_status = {
        name: state['tracks'][name]['checklist_status']
        for name in engine.TRACK_NAMES if state['tracks'][name]['started']
    }

    AIActAssessment.objects.update_or_create(
        session_key=session_key,
        defaults={
            'roles': _combined_roles_list(state),
            'track_results': track_results,
            'answers': answers,
            'checklist_status': checklist_status,
        },
    )


def _all_started_tracks_completed(state):
    started = [name for name in engine.TRACK_NAMES if state['tracks'][name]['started']]
    return bool(started) and all(state['tracks'][name]['completed'] for name in started)


def _sync_trustworthiness(request, state):
    """Mirror the finished AI Act assessment into trustworthiness.Assessment.

    Only fires once every track the user started has completed - ai_system
    and gpai_model can be run independently, and a single-track snapshot
    would otherwise get flagged as the final result of the whole attempt.
    """
    if not _all_started_tracks_completed(state):
        return

    tw_id = request.session.get('ai_act_assessment_id')
    project_id = request.session.get('ai_act_project_id', '')
    if not (tw_id or project_id):
        return

    track_results = {
        name: {
            'risk_category': state['tracks'][name]['risk_category'],
            'role': state['tracks'][name]['role'],
            'answers': state['tracks'][name]['answers'],
            'checklist_status': state['tracks'][name]['checklist_status'],
        }
        for name in engine.TRACK_NAMES if state['tracks'][name]['started']
    }
    tw_result = {
        'roles': _combined_roles_list(state),
        'track_results': track_results,
    }

    if tw_id:
        from trustworthiness.models import Assessment as TWAssessment
        TWAssessment.objects.filter(id=tw_id).update(results=tw_result)
        return

    # project_id is single-use: it only seeds the first Assessment of this
    # attempt, so drop it now rather than letting it leak into a later
    # attempt that doesn't specify its own project.
    request.session.pop('ai_act_project_id', None)
    request.session.modified = True
    try:
        from projects.models import Project
        from trustworthiness.models import Assessment as TWAssessment
        project = Project.objects.get(id=int(project_id))
        if not project.is_accessible_by(request.user):
            logger.warning(
                "User %s denied access to project_id=%s for Assessment creation",
                request.user.id, project_id,
            )
            return
        tw = TWAssessment.objects.create(
            project=project,
            assessment_type=TWAssessment.AssessmentType.AI_ACT,
            status=TWAssessment.Status.COMPLETED,
            input_data={'roles': _combined_roles_list(state)},
            results=tw_result,
        )
        request.session['ai_act_assessment_id'] = tw.id
        request.session.modified = True
    except Exception:
        logger.exception("Failed to create trustworthiness Assessment for project_id=%s", project_id)


@login_required
def intro(request):
    """
    The questionnaire always starts on the ai_system track (AI-1.1); the
    gpai_model track is only ever reached from within that flow (AI-1.2, or
    a manual opt-in from the results screen) - so there is a single primary
    entry action here, not a choice between two tracks.
    """
    project_id = request.GET.get('project_id', '')
    if project_id:
        request.session['ai_act_project_id'] = project_id
        request.session.pop('ai_act_assessment_id', None)
        request.session.modified = True

    state = _get_state(request)
    entry_track = state['active_track'] or 'ai_system'
    entry_state = state['tracks'][entry_track]

    if entry_state['started'] and not entry_state['completed']:
        entry_action = 'resume'
    elif any(state['tracks'][name]['completed'] for name in engine.TRACK_NAMES):
        entry_action = 'results'
    else:
        entry_action = 'start'
        entry_track = 'ai_system'

    return render(request, 'questionnaire/intro.html', {
        'metadata': engine.get_metadata(),
        'entry_action': entry_action,
        'entry_track': entry_track,
        'entry_step': entry_state['current_step'],
        'has_existing': entry_action != 'start',
    })


@login_required
def start_track(request, track):
    if track not in engine.TRACK_NAMES:
        return HttpResponseBadRequest('Unknown track')

    state = _get_state(request)
    track_state = _empty_track_state()
    track_state['started'] = True
    track_state['current_step'] = engine.first_step_id(track)
    state['tracks'][track] = track_state
    state['active_track'] = track
    _save_state(request, state)
    return redirect('questionnaire:step', track=track, step_id=track_state['current_step'])


@login_required
def step_view(request, track, step_id):
    if track not in engine.TRACK_NAMES:
        return HttpResponseBadRequest('Unknown track')

    state = _get_state(request)
    track_state = state['tracks'][track]
    if not track_state['started'] or track_state['current_step'] != step_id:
        # Session doesn't know about this step (fresh visit / stale bookmark) - restart the track.
        return redirect('questionnaire:start_track', track=track)

    state['active_track'] = track
    _save_state(request, state)

    step = engine.get_step(track, step_id)
    if step is None:
        return HttpResponseBadRequest('Unknown step')

    total_steps = len(engine.get_steps(track))
    other_track = 'gpai_model' if track == 'ai_system' else 'ai_system'
    context = {
        'track': track,
        'track_label': engine.get_track_label(track),
        'step': step,
        'track_state': track_state,
        'progress_index': engine.step_position(track, step_id) or total_steps,
        'progress_total': total_steps,
        'other_track': other_track,
        'other_track_label': engine.get_track_label(other_track),
        'other_track_started': state['tracks'][other_track]['started'],
    }

    if step['type'] == 'checklist':
        context['checklist_status'] = track_state['checklist_status'].get(step_id, {})
        context['gp4a_answer'] = track_state['answers'].get('GP-4a') if step_id == 'GP-4b' else None
        return render(request, 'questionnaire/step_checklist.html', context)

    context['selected_answer'] = track_state['answers'].get(step_id)
    return render(request, 'questionnaire/step_branching.html', context)


@login_required
def submit_branching(request, track, step_id):
    if request.method != 'POST':
        return redirect('questionnaire:step', track=track, step_id=step_id)

    state = _get_state(request)
    track_state = state['tracks'][track]
    if track_state['current_step'] != step_id:
        return redirect('questionnaire:start_track', track=track)

    step = engine.get_step(track, step_id)
    answer_value = request.POST.get('answer')
    chosen = next((opt for opt in step['answer_options'] if opt['value'] == answer_value), None)
    if chosen is None:
        return redirect('questionnaire:step', track=track, step_id=step_id)

    track_state['answers'][step_id] = answer_value
    hints = chosen.get('derived_hints') or {}

    if hints.get('sets_role'):
        track_state['role'] = hints['sets_role']
    if hints.get('risk_category'):
        track_state['risk_category'] = hints['risk_category']

    gpai_category = engine.gpai_risk_classification(step_id, answer_value)
    if gpai_category:
        track_state['risk_category'] = gpai_category

    switches_track = hints.get('switches_track')
    next_step_id = engine.resolve_next(track, step_id, hints, track_state['risk_category'])

    _push_history(track_state, step_id)

    if next_step_id:
        _advance_track(track_state, track, next_step_id)
        # "Not sure" answers carry actual guidance (consult someone, assume a
        # default, etc.), unlike plain YES/NO whose next_step_raw just repeats
        # the destination's label - so only these are worth flashing.
        if answer_value.strip().upper().startswith('NOT SURE'):
            track_state['flash_note'] = chosen.get('next_step_raw')
    else:
        track_state['completed'] = True
        track_state['current_step'] = None
        # No further step to flash it on - keep it for the results screen instead.
        track_state['terminal_note'] = chosen.get('next_step_raw')

    if track_state['completed'] and switches_track in engine.TRACK_NAMES and switches_track != track:
        # A full hand-off to the other track (as opposed to "do both") means
        # this track's determination doesn't apply after all - drop it so it
        # doesn't show up as an empty/void result on the results screen later.
        state['tracks'][track] = _empty_track_state()
        other = state['tracks'][switches_track]
        _save_state(request, state)
        if not other['started']:
            return redirect('questionnaire:start_track', track=switches_track)
        if other['completed']:
            return redirect('questionnaire:results')
        return redirect('questionnaire:step', track=switches_track, step_id=other['current_step'])

    _save_state(request, state)

    if track_state['completed']:
        _persist_snapshot(request, state)
        _sync_trustworthiness(request, state)
        if switches_track == 'both':
            for name in engine.TRACK_NAMES:
                if not state['tracks'][name]['started']:
                    return redirect('questionnaire:start_track', track=name)
        return redirect('questionnaire:results')

    if track_state.get('flash_note'):
        return redirect('questionnaire:not_sure_notice', track=track)

    return redirect('questionnaire:step', track=track, step_id=track_state['current_step'])


@login_required
def not_sure_notice(request, track):
    if track not in engine.TRACK_NAMES:
        return HttpResponseBadRequest('Unknown track')

    state = _get_state(request)
    track_state = state['tracks'][track]
    message = track_state.pop('flash_note', None)
    _save_state(request, state)

    if not message or not track_state['current_step']:
        return redirect('questionnaire:step', track=track, step_id=track_state['current_step']) \
            if track_state['current_step'] else redirect('questionnaire:start_track', track=track)

    first_step_id = engine.first_step_id(track)
    return render(request, 'questionnaire/not_sure.html', {
        'track': track,
        'track_label': engine.get_track_label(track),
        'message': message,
        'continue_step_id': track_state['current_step'],
        'continue_step_label': engine.get_step(track, track_state['current_step'])['step_label'],
        'restart_step_label': engine.get_step(track, first_step_id)['step_label'],
    })


@login_required
def submit_checklist(request, track, step_id):
    if request.method != 'POST':
        return redirect('questionnaire:step', track=track, step_id=step_id)

    state = _get_state(request)
    track_state = state['tracks'][track]
    if track_state['current_step'] != step_id:
        return redirect('questionnaire:start_track', track=track)

    step = engine.get_step(track, step_id)
    valid_statuses = set(step['status_options'])
    statuses = track_state['checklist_status'].setdefault(step_id, {})
    for item in step['items']:
        value = request.POST.get(f"item_{item['item_id']}")
        if value in valid_statuses:
            statuses[item['item_id']] = value

    _push_history(track_state, step_id)
    _finish_current_step(track_state)
    _save_state(request, state)

    if track_state['completed']:
        _persist_snapshot(request, state)
        _sync_trustworthiness(request, state)
        return redirect('questionnaire:results')

    return redirect('questionnaire:step', track=track, step_id=track_state['current_step'])


@login_required
def back_step(request, track):
    if track not in engine.TRACK_NAMES:
        return HttpResponseBadRequest('Unknown track')

    state = _get_state(request)
    track_state = state['tracks'][track]
    if not track_state['history']:
        return redirect('questionnaire:intro')

    previous_step_id = track_state['history'].pop()
    track_state['current_step'] = previous_step_id
    track_state['completed'] = False
    _save_state(request, state)
    return redirect('questionnaire:step', track=track, step_id=previous_step_id)


@login_required
def results(request):
    state = _get_state(request)
    tracks_data = {}
    for name in engine.TRACK_NAMES:
        track_state = state['tracks'][name]
        if not track_state['started']:
            continue
        risk_category = track_state['risk_category']
        tracks_data[name] = {
            'label': engine.get_track_label(name),
            'role': track_state['role'],
            'risk_category': risk_category,
            'is_terminal': risk_category in engine.TERMINAL_RISK_CATEGORIES,
            'completed': track_state['completed'],
            'current_step': track_state['current_step'],
            'terminal_note': track_state.get('terminal_note'),
            'obligations': engine.compute_obligations(
                name, risk_category, track_state['role'], track_state['checklist_status'],
                track_state['answers']
            ) if track_state['completed'] else [],
        }

    return render(request, 'questionnaire/results.html', {
        'tracks_data': tracks_data,
        'roles': _combined_roles_list(state),
        'has_snapshot': bool(request.session.session_key and AIActAssessment.objects.filter(
            session_key=request.session.session_key).exists()),
    })


@login_required
def restart(request):
    request.session.pop(SESSION_KEY, None)
    request.session.pop('ai_act_project_id', None)
    request.session.pop('ai_act_assessment_id', None)
    request.session.modified = True
    return redirect('questionnaire:start_track', track='ai_system')


@login_required
def download_assessment_json(request):
    session_key = request.session.session_key
    assessment = AIActAssessment.objects.filter(session_key=session_key).first() if session_key else None
    if not assessment:
        return HttpResponse('No completed assessment found.', status=404)

    obligations = {
        track: engine.compute_obligations(
            track,
            assessment.track_results.get(track, {}).get('risk_category'),
            assessment.track_results.get(track, {}).get('role'),
            assessment.checklist_status.get(track, {}),
            assessment.answers.get(track, {}),
        )
        for track in assessment.track_results
    }

    export_data = {
        'report_id': assessment.id,
        'completion_date': assessment.created_at.isoformat(),
        'roles': assessment.roles,
        'track_results': assessment.track_results,
        'answers': assessment.answers,
        'checklist_status': assessment.checklist_status,
        'obligations': obligations,
    }

    response = HttpResponse(
        json.dumps(export_data, indent=4, ensure_ascii=False),
        content_type='application/json'
    )
    response['Content-Disposition'] = f'attachment; filename="AI_Act_Assessment_{assessment.id}.json"'
    return response
