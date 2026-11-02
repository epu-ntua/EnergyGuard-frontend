import logging

from django.conf import settings
from django.core.mail import mail_admins, send_mail
from django.utils import timezone

from core.services.notifications import platform_link

from .models import PrivacyRequest, TeamInvite
from .services.privacy_requests import PRIVACY_TAB_URL

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


def _admin_link(privacy_request):
    return platform_link(f"/admin/accounts/privacyrequest/{privacy_request.pk}/change/")


def _note(privacy_request):
    return f"\n\nNote from the EnergyGuard team:\n{privacy_request.admin_note}" if privacy_request.admin_note else ""


def _send_to_user(privacy_request, subject, body):
    try:
        send_mail(
            subject=f"[EnergyGuard] {subject}",
            message=f"Hello,\n\n{body}\n\nBest regards,\nThe EnergyGuard Team",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[privacy_request.email],
        )
    except Exception:
        logger.exception("Failed to send '%s' email for privacy request %s", subject, privacy_request.pk)


def _send_to_admins(privacy_request, subject, body):
    try:
        mail_admins(subject=f"[EnergyGuard] {subject}", message=body)
    except Exception:
        logger.exception("Failed to send '%s' email to admins for privacy request %s", subject, privacy_request.pk)


def send_privacy_request_emails(request_id):
    """Notifies the admins of a new GDPR request and confirms receipt to the user."""
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    kind = privacy_request.get_kind_display().lower()
    _send_to_admins(
        privacy_request,
        f"Privacy request: {kind} ({privacy_request.email})",
        f"{privacy_request.email} has requested a {kind}.\n\n"
        f"Message from the user:\n{privacy_request.message or '-'}\n\n"
        f"Handle it here: {_admin_link(privacy_request)}",
    )
    _send_to_user(
        privacy_request,
        "We received your privacy request",
        f"We have received your request for a {kind}. "
        f"We will process it and get back to you within one month, as provided by the GDPR.\n\n"
        f"You can follow its status in the Privacy tab of your EnergyGuard profile.",
    )


def send_privacy_request_approved_email(request_id):
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    _send_to_user(
        privacy_request,
        "Your account will be deleted",
        f"Your request for the deletion of your personal data has been approved. "
        f"Your EnergyGuard account and the personal data associated with it will be permanently deleted "
        f"on {privacy_request.scheduled_for:%d %B %Y}.\n\n"
        f"Until then you can download a copy of your data from the Privacy tab of your profile, "
        f"or cancel the request there if you have changed your mind:\n{platform_link(PRIVACY_TAB_URL)}"
        f"{_note(privacy_request)}",
    )


def send_privacy_request_rejected_email(request_id):
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    _send_to_user(
        privacy_request,
        "Update on your privacy request",
        f"Your request for a {privacy_request.get_kind_display().lower()} has been rejected.{_note(privacy_request)}",
    )


def send_account_deleted_email(request_id):
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    _send_to_user(
        privacy_request,
        "Your account has been deleted",
        "As you requested, your EnergyGuard account and the personal data associated with it "
        "have been permanently deleted.",
    )


def send_privacy_request_cancelled_email(request_id):
    """Tells the admins, who may already be planning an approved deletion."""
    privacy_request = PrivacyRequest.objects.filter(pk=request_id).first()
    if privacy_request is None:
        return

    _send_to_admins(
        privacy_request,
        f"Privacy request cancelled ({privacy_request.email})",
        f"{privacy_request.email} has cancelled their request for a {privacy_request.get_kind_display().lower()}. "
        f"No action is needed.\n\n{_admin_link(privacy_request)}",
    )


def remind_admins_of_due_deletions():
    """Daily: emails the admins the approved deletions scheduled for today."""
    due = list(PrivacyRequest.objects.filter(
        status=PrivacyRequest.Status.APPROVED, scheduled_for=timezone.localdate(),
    ).order_by('created_at'))
    if not due:
        return

    lines = "\n".join(f"- {pr.email}: {_admin_link(pr)}" for pr in due)
    try:
        mail_admins(
            subject=f"[EnergyGuard] {len(due)} account deletion(s) due today",
            message=(
                f"These accounts are scheduled for deletion today. Open each request "
                f"and use \"Delete account now\":\n\n{lines}"
            ),
        )
    except Exception:
        logger.exception("Failed to send the due deletions reminder for %s request(s)", len(due))
