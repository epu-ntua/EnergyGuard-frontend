"""
Self-service GDPR export (Art. 15/20): everything the platform stores about a user,
as a zip with personal_data.json (portable), personal_data.html (readable copy of
the same data) and the profile picture.

Third parties are left out on purpose (who invited the user, project collaborators,
invitee emails), since Art. 15(4) says the copy must not affect the rights of others.
Dataset files and digital twin results are not bundled: they can be large, and the
user can already download them from the platform. Their metadata is listed instead.
"""
import datetime
import io
import json
import logging
import os
import zipfile

from django.core.serializers.json import DjangoJSONEncoder
from django.template.loader import render_to_string
from django.utils import timezone

from billing.models import Billing, PaymentMethod
from datasets.models import Dataset, DatasetUserDownload
from digitaltwins.models import BerExperimentRequest, DtExport, DtRun, RdnSimulationJob
from projects.models import Experiment, Project, ProjectCollaborator

from ..models import Notification, PrivacyRequest, Profile, TeamInvite

logger = logging.getLogger(__name__)


def _rows(queryset, *fields):
    return list(queryset.values(*fields))


def collect_user_data(user):
    profile = Profile.objects.select_related('team').filter(user=user).first()

    return {
        'exported_at': timezone.now(),
        'account': {
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_joined': user.date_joined,
            'last_login': user.last_login,
            'membership': user.get_membership_display(),
            'credits': user.credits,
        },
        'profile': {
            'bio': profile.bio,
            'position': profile.position,
            'birth_date': profile.birth_date,
            'profile_picture': os.path.basename(profile.profile_picture.name) if profile.profile_picture else None,
            'team': profile.team.name if profile.team else None,
            'team_role': profile.team_role,
            'team_joined_at': profile.team_joined_at,
        } if profile else None,
        'team_invites_received': _rows(
            TeamInvite.objects.filter(email__iexact=user.email),
            'team__name', 'created_at', 'expires_at', 'accepted_at', 'declined_at',
        ),
        'team_invites_sent': _rows(
            TeamInvite.objects.filter(invited_by=user),
            'team__name', 'created_at', 'accepted_at', 'declined_at',
        ),
        'notifications': _rows(Notification.objects.filter(recipient=user), 'message', 'is_read', 'created_at'),
        'projects_created': _rows(
            Project.objects.filter(creator=user),
            'name', 'project_type', 'description', 'visibility', 'created_at', 'updated_at',
        ),
        'project_collaborations': _rows(
            ProjectCollaborator.objects.filter(collaborator=user),
            'project__name', 'permission_level', 'created_at',
        ),
        'experiments_created': _rows(
            Experiment.objects.filter(creator=user),
            'name', 'project__name', 'description', 'created_at',
        ),
        'datasets_published': _rows(
            Dataset.objects.filter(publisher=user),
            'name', 'description', 'label', 'source', 'status', 'rejection_reason', 'visibility', 'size_gb',
            'submitted_at', 'reviewed_at', 'created_at',
        ),
        'dataset_downloads': _rows(DatasetUserDownload.objects.filter(user=user), 'dataset__name', 'created_at'),
        'digital_twin_runs': _rows(
            DtRun.objects.filter(user=user),
            'twin_slug', 'operation', 'inputs', 'status', 'error_message', 'created_at',
        ),
        'digital_twin_exports': _rows(DtExport.objects.filter(user=user), 'twin_slug', 'created_at'),
        'ber_experiment_requests': _rows(
            BerExperimentRequest.objects.filter(user=user),
            'experiment_json', 'status', 'rejection_reason', 'actual_start', 'actual_end', 'cancelled_at', 'created_at',
        ),
        'rdn_simulation_jobs': _rows(
            RdnSimulationJob.objects.filter(user=user),
            'use_case', 'grid_section', 'assets', 'status', 'created_at',
        ),
        'invoices': _rows(
            Billing.objects.filter(customer=user),
            'invoice', 'billing_period_start', 'billing_period_end', 'amount', 'currency', 'plan_type', 'payment_status', 'created_at',
        ),
        # Never export full card numbers or CVV, only enough to recognise the card
        'payment_methods': [
            {
                'cardholder_name': pm.cardholder_name,
                'card_last4': (pm.card_number or '')[-4:] or None,
                'expiration': f'{pm.expiration_month}/{pm.expiration_year}' if pm.expiration_month else None,
                'created_at': pm.created_at,
            }
            for pm in PaymentMethod.objects.filter(user=user)
        ],
        'privacy_requests': _rows(
            PrivacyRequest.objects.filter(user=user),
            'kind', 'status', 'message', 'admin_note', 'scheduled_for', 'created_at', 'resolved_at',
        ),
    }


# Order and headings of the HTML copy; keys match collect_user_data()
SECTION_TITLES = {
    'account': 'Account',
    'profile': 'Profile',
    'team_invites_received': 'Team invitations received',
    'team_invites_sent': 'Team invitations sent',
    'projects_created': 'Projects you created',
    'project_collaborations': 'Projects you collaborate on',
    'experiments_created': 'Experiments you created',
    'datasets_published': 'Datasets you published',
    'dataset_downloads': 'Datasets you downloaded',
    'digital_twin_runs': 'Digital twin runs',
    'digital_twin_exports': 'Digital twin results exported to JupyterHub',
    'ber_experiment_requests': 'BER experiment requests',
    'rdn_simulation_jobs': 'RDN simulation jobs',
    'invoices': 'Invoices',
    'payment_methods': 'Payment methods',
    'privacy_requests': 'Deletion requests',
    'notifications': 'Notifications',
}


def _heading(key):
    # 'team__name' -> 'Team', 'card_last4' -> 'Card last4'
    return key.split('__')[0].replace('_', ' ').capitalize()


def _cell(value):
    """Returns (text, is_preformatted) for one HTML table cell."""
    if value is None or value == '':
        return '-', False
    if isinstance(value, bool):
        return ('Yes' if value else 'No'), False
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).strftime('%d %b %Y, %H:%M') if timezone.is_aware(value) else value.strftime('%d %b %Y, %H:%M'), False
    if isinstance(value, datetime.date):
        return value.strftime('%d %b %Y'), False
    if isinstance(value, (dict, list)):
        return json.dumps(value, cls=DjangoJSONEncoder, indent=2, ensure_ascii=False), True
    return str(value), False


def _html_sections(data):
    sections = []
    for key, title in SECTION_TITLES.items():
        value = data.get(key)
        if isinstance(value, dict):
            sections.append({'title': title, 'kind': 'fields',
                             'fields': [(_heading(k), _cell(v)) for k, v in value.items()]})
        elif isinstance(value, list):
            headers = [_heading(k) for k in value[0]] if value else []
            rows = [[_cell(v) for v in row.values()] for row in value]
            sections.append({'title': title, 'kind': 'table', 'headers': headers, 'rows': rows})
        else:
            sections.append({'title': title, 'kind': 'empty'})
    return sections


def build_user_data_export(user):
    """Returns the export zip as bytes."""
    data = collect_user_data(user)
    html = render_to_string('accounts/data_export.html', {
        'user': user,
        'exported_at': _cell(data['exported_at'])[0],
        'sections': _html_sections(data),
    })

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('personal_data.json', json.dumps(data, cls=DjangoJSONEncoder, indent=2, ensure_ascii=False))
        archive.writestr('personal_data.html', html)

        profile = Profile.objects.filter(user=user).first()
        if profile and profile.profile_picture:
            try:
                with profile.profile_picture.open('rb') as picture:
                    archive.writestr(f'profile_picture/{os.path.basename(profile.profile_picture.name)}', picture.read())
            except Exception:
                # A missing file shouldn't block the rest of the export
                logger.exception('Could not add profile picture to data export for user %s', user.pk)
    return buffer.getvalue()
