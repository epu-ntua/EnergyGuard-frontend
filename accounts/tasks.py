import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import TeamInvite

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
