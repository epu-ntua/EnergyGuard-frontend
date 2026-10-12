import logging

from django.conf import settings
from django.core.mail import mail_admins, send_mail

from .models import PrivacyRequest, TeamInvite

logger = logging.getLogger(__name__)

INVITE_EXPIRY_DAYS = 14


def send_team_invite_email(invite_id, platform_url, inviter_name):
    """Runs in the qcluster worker, not the web process - a slow/unreachable SMTP
    server must never stall the admin's send-invite request (see send_team_invite)."""
    invite = TeamInvite.objects.select_related("team").filter(pk=invite_id).first()
    if invite is None:
        return

    try:
        send_mail(
            subject=f"You've been invited to join {invite.team.name} on EnergyGuard",
            message=(
                f"Hi,\n\n"
                f"{inviter_name} has invited you to join the team '{invite.team.name}' on EnergyGuard.\n\n"
                f"To accept or decline the invitation, sign in to EnergyGuard and go to Team Management:\n{platform_url}\n\n"
                f"If you don't have an account yet, sign in with Keycloak at the link above to get started.\n\n"
                f"This invitation expires in {INVITE_EXPIRY_DAYS} days.\n\n"
                f"Best regards,\nThe EnergyGuard Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invite.email],
        )
    except Exception:
        logger.exception("Failed to send team invite email for invite %s", invite.pk)


def send_privacy_request_emails(request_id, admin_url):
    """Notifies the admins of a new GDPR request and confirms receipt to the user."""
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    kind = privacy_request.get_kind_display().lower()
    try:
        mail_admins(
            subject=f"[EnergyGuard] Privacy request: {kind} ({privacy_request.email})",
            message=(
                f"{privacy_request.email} has requested a {kind}.\n\n"
                f"Message from the user:\n{privacy_request.message or '-'}\n\n"
                f"Handle it here: {admin_url}"
            ),
        )
    except Exception:
        logger.exception("Failed to notify admins of privacy request %s", privacy_request.pk)

    try:
        send_mail(
            subject="[EnergyGuard] We received your privacy request",
            message=(
                f"Hello,\n\n"
                f"We have received your request for a {kind}. "
                f"We will process it and get back to you within one month, as provided by the GDPR.\n\n"
                f"You can follow its status in the Privacy tab of your EnergyGuard profile.\n\n"
                f"Best regards,\nThe EnergyGuard Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[privacy_request.email],
        )
    except Exception:
        logger.exception("Failed to send privacy request confirmation for request %s", privacy_request.pk)


def send_privacy_request_resolved_email(request_id):
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    note = f"\n\nNote from the EnergyGuard team:\n{privacy_request.admin_note}" if privacy_request.admin_note else ""
    try:
        send_mail(
            subject="[EnergyGuard] Update on your privacy request",
            message=(
                f"Hello,\n\n"
                f"Your request for a {privacy_request.get_kind_display().lower()} "
                f"has been {privacy_request.get_status_display().lower()}.{note}\n\n"
                f"Best regards,\nThe EnergyGuard Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[privacy_request.email],
        )
    except Exception:
        logger.exception("Failed to send privacy request resolution email for request %s", privacy_request.pk)
