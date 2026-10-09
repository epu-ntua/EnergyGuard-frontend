"""BER background tasks, run by the qcluster worker (enqueued with async_task)."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from accounts.models import Notification
from digitaltwins.models import BerExperimentRequest

from .services.results import build_ber_results_context

logger = logging.getLogger(__name__)


def send_ber_notification_email(experiment_request_id, platform_url):
    """Runs in the qcluster worker, not the web process - a slow/unreachable SMTP
    server must never stall the user's submit request (see ber_experiment_submit)."""
    experiment_request = BerExperimentRequest.objects.filter(pk=experiment_request_id).first()
    if experiment_request is None or not settings.BER_EMAIL:
        return

    management_path = reverse('ber-management-detail', args=[experiment_request.pk])

    try:
        send_mail(
            subject=f'New BER experiment request #{experiment_request.pk} — EnergyGuard',
            message=(
                f'A new PEM electrolyzer experiment request has been submitted on EnergyGuard.\n\n'
                f'Request ID: {experiment_request.pk}\n'
                f'Submitted by: {experiment_request.user.email}\n'
                f'Submitted at: {experiment_request.created_at.strftime("%Y-%m-%d %H:%M UTC")}\n\n'
                f'Review it here:\n{platform_url.rstrip("/")}{management_path}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.BER_EMAIL],
        )
    except Exception:
        logger.exception('Failed to send BER notification email for request %s', experiment_request.pk)


def warm_ber_results_cache(experiment_request_id):
    """Runs in the qcluster worker right after BER uploads a result file: parses the
    .lp and fills the results cache, so the requester's first view (usually from the
    notification link) doesn't pay the multi-second parse."""
    experiment_request = BerExperimentRequest.objects.filter(pk=experiment_request_id).first()
    if (experiment_request is None or experiment_request.status != BerExperimentRequest.Status.COMPLETED
            or not experiment_request.result_key):
        return

    try:
        build_ber_results_context(experiment_request)
    except Exception:
        # The results page retries the same build on first view and shows the
        # requester a proper message if it fails there too.
        logger.exception('Could not pre-build BER results for request %s', experiment_request.pk)


def send_ber_cancellation_email(experiment_request_id, platform_url):
    """Runs in the qcluster worker - tells BER staff a requester withdrew a pending
    request, so the lab doesn't run it (see ber_hydrogen_request_cancel)."""
    experiment_request = BerExperimentRequest.objects.filter(pk=experiment_request_id).select_related('user').first()
    if experiment_request is None or not settings.BER_EMAIL:
        return

    management_path = reverse('ber-management-detail', args=[experiment_request.pk])

    try:
        send_mail(
            subject=f'BER experiment request #{experiment_request.pk} cancelled — EnergyGuard',
            message=(
                f'A PEM electrolyzer experiment request has been cancelled by its requester '
                f'and no longer needs to be run.\n\n'
                f'Request ID: {experiment_request.pk}\n'
                f'Submitted by: {experiment_request.user.email}\n'
                f'Submitted at: {experiment_request.created_at.strftime("%Y-%m-%d %H:%M UTC")}\n\n'
                f'View it here:\n{platform_url.rstrip("/")}{management_path}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.BER_EMAIL],
        )
    except Exception:
        logger.exception('Failed to send BER cancellation email for request %s', experiment_request.pk)


def notify_ber_results_updated(experiment_request_id, platform_url):
    """Runs in the qcluster worker - tells the requester BER staff replaced the
    result file of their completed request (see ber_management_replace_result)."""
    experiment_request = BerExperimentRequest.objects.filter(pk=experiment_request_id).select_related('user').first()
    if experiment_request is None or experiment_request.status != BerExperimentRequest.Status.COMPLETED:
        return

    detail_path = reverse('ber-hydrogen-request-detail', args=[experiment_request.pk])

    Notification.objects.create(
        recipient=experiment_request.user,
        message=f'The results of your BER experiment request #{experiment_request.pk} were updated',
        url=detail_path,
        icon='rotate',
    )

    try:
        send_mail(
            subject=f'Updated results for your BER experiment request #{experiment_request.pk} — EnergyGuard',
            message=(
                f'Hi,\n\n'
                f'The BER laboratory team has uploaded an updated result file for your PEM electrolyzer '
                f'experiment request #{experiment_request.pk}. The results shown on EnergyGuard now reflect it.\n\n'
                f'View them here:\n{platform_url.rstrip("/")}{detail_path}\n\n'
                f'Best regards,\nThe EnergyGuard Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[experiment_request.user.email],
        )
    except Exception:
        logger.exception('Failed to send BER results-updated email for request %s', experiment_request.pk)


def notify_ber_request_decision(experiment_request_id, platform_url):
    """Runs in the qcluster worker - notifies the requester once BER staff marks
    their request completed or rejected (see ber_management_detail)."""
    experiment_request = BerExperimentRequest.objects.filter(pk=experiment_request_id).select_related('user').first()
    if experiment_request is None:
        return

    if experiment_request.status == BerExperimentRequest.Status.COMPLETED:
        subject_verb, body_line, icon = 'is complete', 'Your experiment results are now available.', 'circle-check'
    elif experiment_request.status == BerExperimentRequest.Status.REJECTED:
        subject_verb, body_line, icon = 'was rejected', 'Reason: ' + (experiment_request.rejection_reason or 'No reason given.'), 'circle-xmark'
    else:
        return  # not a terminal decision - nothing to notify about

    detail_path = reverse('ber-hydrogen-request-detail', args=[experiment_request.pk])

    Notification.objects.create(
        recipient=experiment_request.user,
        message=f'Your BER experiment request #{experiment_request.pk} {subject_verb}',
        url=detail_path,
        icon=icon,
    )

    try:
        send_mail(
            subject=f'Your BER experiment request #{experiment_request.pk} {subject_verb} — EnergyGuard',
            message=(
                f'Hi,\n\n'
                f'Your BER PEM electrolyzer experiment request #{experiment_request.pk} {subject_verb}.\n\n'
                f'{body_line}\n\n'
                f'View it here:\n{platform_url.rstrip("/")}{detail_path}\n\n'
                f'Best regards,\nThe EnergyGuard Team'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[experiment_request.user.email],
        )
    except Exception:
        logger.exception('Failed to send BER decision email for request %s', experiment_request.pk)
