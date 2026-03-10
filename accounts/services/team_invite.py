import uuid
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import Notification, Profile, TeamInvite, User

INVITE_EXPIRY_DAYS = 14


def send_team_invite(request, team, email, invited_by):
    """
    Creates a TeamInvite and sends an invitation email.
    Returns (invite, error_message). On success error_message is None.
    """
    # Already a member?
    if Profile.objects.filter(user__email=email, team=team).exists():
        return None, "This user is already a member of your team."

    # Pending non-expired invite already exists (not declined)?
    existing = TeamInvite.objects.filter(team=team, email=email, accepted_at__isnull=True).first()
    if existing and not existing.is_expired and not existing.is_declined:
        return None, "An invitation has already been sent to this email."

    # Refresh expired/declined invite or create new one
    if existing:
        existing.token = uuid.uuid4()
        existing.expires_at = timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS)
        existing.invited_by = invited_by
        existing.declined_at = None
        existing.save()
        invite = existing
    else:
        invite = TeamInvite.objects.create(
            team=team,
            email=email,
            invited_by=invited_by,
            expires_at=timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS),
        )

    platform_url = request.build_absolute_uri(reverse('team_management'))
    inviter_name = invited_by.get_full_name() or invited_by.email

    send_mail(
        subject=f"You've been invited to join {team.name} on EnergyGuard",
        message=(
            f"Hi,\n\n"
            f"{inviter_name} has invited you to join the team '{team.name}' on EnergyGuard.\n\n"
            f"To accept or decline the invitation, sign in to EnergyGuard and go to Team Management:\n{platform_url}\n\n"
            f"If you don't have an account yet, sign in with Keycloak at the link above to get started.\n\n"
            f"This invitation expires in {INVITE_EXPIRY_DAYS} days.\n\n"
            f"Best regards,\nThe EnergyGuard Team"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
    )

    invited_user = User.objects.filter(email=email).first()
    if invited_user:
        Notification.objects.create(
            recipient=invited_user,
            message=f"{inviter_name} invited you to join {team.name}",
            url=reverse('team_management'),
            icon='envelope',
        )

    return invite, None


def decline_team_invite(token, user):
    """
    Declines a team invitation for the given user.
    Returns error_message or None on success.
    """
    try:
        invite = TeamInvite.objects.get(token=token)
    except TeamInvite.DoesNotExist:
        return "Invalid invitation link."

    if invite.is_accepted:
        return "This invitation has already been accepted."

    if user.email != invite.email:
        return "This invitation was sent to a different email address."

    invite.declined_at = timezone.now()
    invite.save()

    decliner_name = user.get_full_name() or user.email
    Notification.objects.create(
        recipient=invite.invited_by,
        message=f"{decliner_name} declined your invite to {invite.team.name}",
        url=reverse('team_management'),
        icon='user-times',
    )

    return None


def accept_team_invite(token, user):
    """
    Accepts a team invitation for the given user.
    Returns (team, error_message). On success error_message is None.
    """
    try:
        invite = TeamInvite.objects.select_related('team').get(token=token)
    except TeamInvite.DoesNotExist:
        return None, "Invalid invitation link."

    if invite.is_accepted:
        return None, "This invitation has already been used."

    if invite.is_expired:
        return None, "This invitation has expired. Please ask your team admin to send a new one."

    if user.email != invite.email:
        return None, "This invitation was sent to a different email address."

    profile = user.profile
    if profile.team is not None:
        return None, "You are already part of a team."

    profile.team = invite.team
    profile.team_role = Profile.Team_Role.MEMBER
    profile.team_joined_at = timezone.now()
    profile.save()

    invite.accepted_at = timezone.now()
    invite.save()

    accepter_name = user.get_full_name() or user.email
    Notification.objects.create(
        recipient=invite.invited_by,
        message=f"{accepter_name} accepted your invite to {invite.team.name}",
        url=reverse('team_management'),
        icon='user-check',
    )

    return invite.team, None
