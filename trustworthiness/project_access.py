"""Every assessment run belongs to a project the user can edit.

The assessment flows carry the project picked in the hub (in the URL and the
form, or in the session for the AI Act questionnaire). An entry without a
usable project goes back to the hub's project picker instead of running a job
that no Assessment would record.
"""

import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)


def editable_project(user, project_id):
    """The project `project_id` names, or None when it is missing, unknown, or
    the user may not write to it (creating an assessment writes to the project:
    read access to a public project is not enough)."""
    from projects.models import Project

    if not project_id:
        return None
    try:
        project = Project.objects.get(id=int(project_id))
    except (Project.DoesNotExist, TypeError, ValueError):
        logger.warning("User %s sent unknown project_id=%s to an assessment", user.id, project_id)
        return None
    if not project.can_edit(user):
        logger.warning("User %s denied write access to project_id=%s for an assessment", user.id, project_id)
        return None
    return project


def assessment_project_id(assessment_id):
    """The project of a running job's Assessment, so the job's pages can link
    back to the form for the same project; None when there is none."""
    from .models import Assessment

    if not assessment_id:
        return None
    return Assessment.objects.filter(id=assessment_id).values_list('project_id', flat=True).first()


def project_picker_redirect(request, assessment_type):
    """The hub, with the project picker open for `assessment_type` and a
    message saying why the user landed there.

    The hub matches `open_modal` against its cards' names, which are the
    AssessmentType labels.
    """
    messages.warning(request, f"Choose a project you can edit to start the {assessment_type.label}.")
    query = urlencode({'open_modal': assessment_type.label})
    return redirect(f"{reverse('trustworthiness:trustworthiness')}?{query}")
