import datetime
import logging

from allauth.socialaccount.models import SocialAccount
from django.db import IntegrityError, transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from django_q.tasks import async_task

from core.services.notifications import notify_in_app

from ..models import PrivacyRequest, Profile, TeamInvite
from .keycloak_user_sync import KeycloakUserSyncClient

logger = logging.getLogger(__name__)

# Time between approval and deletion, for the user to download their data or change their mind
DELETION_GRACE_DAYS = 2

PRIVACY_TAB_URL = '/accounts/profile/?tab=privacy'


class AccountDeletionError(Exception):
    pass


def submit_privacy_request(user, kind, message=""):
    """
    Records a GDPR request for user and notifies the admins.
    Idempotent: if an open request of the same kind exists it is returned as-is.
    Returns (privacy_request, created).
    """
    open_requests = PrivacyRequest.objects.filter(user=user, kind=kind, status__in=PrivacyRequest.OPEN_STATUSES)
    existing = open_requests.first()
    if existing:
        return existing, False

    try:
        with transaction.atomic():
            privacy_request = PrivacyRequest.objects.create(
                user=user, email=user.email, kind=kind, message=message.strip(),
            )
    except IntegrityError:
        # A concurrent submit won the unique_open_privacy_request race
        return open_requests.get(), False

    transaction.on_commit(lambda: async_task('accounts.tasks.send_privacy_request_emails', privacy_request.pk))
    return privacy_request, True


def _transition(privacy_request, from_status, **changes):
    """Applies changes only if the request is still in from_status, so a double click
    or a cancel landing at the same time can't apply twice. Returns whether it did."""
    updated = PrivacyRequest.objects.filter(pk=privacy_request.pk, status=from_status).update(
        updated_at=timezone.now(), **changes,
    )
    if updated:
        for field, value in changes.items():
            setattr(privacy_request, field, value)
    return updated > 0


def cancel_privacy_request(user, request_id):
    """Cancels the user's own open request. Returns True if something was cancelled."""
    privacy_request = PrivacyRequest.objects.filter(
        pk=request_id, user=user, status__in=PrivacyRequest.OPEN_STATUSES,
    ).first()
    if privacy_request is None:
        return False
    if not _transition(privacy_request, privacy_request.status,
                       status=PrivacyRequest.Status.CANCELLED, resolved_at=timezone.now()):
        return False

    # The admins may already be planning the deletion
    transaction.on_commit(lambda: async_task('accounts.tasks.send_privacy_request_cancelled_email', privacy_request.pk))
    return True


def approve_privacy_request(privacy_request, approved_by):
    """Admin side: schedules the deletion DELETION_GRACE_DAYS from today and tells the user."""
    scheduled_for = timezone.localdate() + datetime.timedelta(days=DELETION_GRACE_DAYS)
    if not _transition(privacy_request, PrivacyRequest.Status.PENDING,
                       status=PrivacyRequest.Status.APPROVED, scheduled_for=scheduled_for, resolved_by=approved_by):
        return False

    if privacy_request.user:
        notify_in_app(
            privacy_request.user,
            message=f"Your deletion request was approved. Your account will be deleted on {scheduled_for:%d %b %Y}",
            url=PRIVACY_TAB_URL,
            icon='shield-alt',
        )
    transaction.on_commit(lambda: async_task('accounts.tasks.send_privacy_request_approved_email', privacy_request.pk))
    return True


def reject_privacy_request(privacy_request, rejected_by):
    """Admin side: rejects a pending request and tells the user."""
    if not _transition(privacy_request, PrivacyRequest.Status.PENDING,
                       status=PrivacyRequest.Status.REJECTED, resolved_at=timezone.now(), resolved_by=rejected_by):
        return False

    if privacy_request.user:
        notify_in_app(
            privacy_request.user,
            message=f"Your request for {privacy_request.get_kind_display().lower()} was rejected",
            url=PRIVACY_TAB_URL,
            icon='shield-alt',
        )
    transaction.on_commit(lambda: async_task('accounts.tasks.send_privacy_request_rejected_email', privacy_request.pk))
    return True


def delete_account(privacy_request, deleted_by):
    """
    Admin side: deletes the account of an approved request whose day has come,
    from Django and from Keycloak, and emails the user that it is done.

    Django first, inside the transaction, then Keycloak: if Keycloak fails the
    Django delete is rolled back and the admin can retry. The other order could
    leave a Keycloak account with no Django user, whose next sign-in would
    create a fresh account. The user's files go with the rows, through the
    post_delete signals, once the delete commits.
    If the user is their team's admin, the member who joined first takes over;
    a team left with no members is deleted.
    Raises AccountDeletionError, with a message for the admin, if nothing was deleted.
    """
    # The token request goes out before the transaction, so a slow Keycloak
    # can't hold the locks the delete takes
    keycloak = KeycloakUserSyncClient()
    if not keycloak.token:
        raise AccountDeletionError("Could not authenticate with Keycloak. Nothing was deleted, please try again.")

    with transaction.atomic():
        # Locked so a cancel landing now waits, then finds the request completed
        locked = PrivacyRequest.objects.select_for_update(of=('self',)).select_related('user').get(pk=privacy_request.pk)
        if not locked.is_due:
            raise AccountDeletionError("Only an approved request can be deleted, from its scheduled day on.")
        user = locked.user
        if user is None:
            raise AccountDeletionError("This account no longer exists.")
        if user.pk == deleted_by.pk:
            raise AccountDeletionError("You cannot delete your own account from here.")

        # Read before the delete, which takes the SocialAccount and Profile with it
        keycloak_user_id = SocialAccount.objects.filter(user=user, provider='keycloak').values_list('uid', flat=True).first()
        profile = Profile.objects.filter(user=user).select_related('team').first()
        team = profile.team if profile else None
        new_team_admin = _next_team_admin(profile)
        user_pk = user.pk

        # Invitations the user received are addressed to their email, not linked to the account
        TeamInvite.objects.filter(email__iexact=user.email).delete()
        user.delete()

        if team and not team.members.exists():
            # Nobody left: the team goes too, with the invitations it sent
            team.delete()
        elif new_team_admin:
            # After the delete: unique_team_admin allows one admin per team
            Profile.objects.filter(pk=new_team_admin.pk).update(team_role=Profile.Team_Role.ADMIN)
            notify_in_app(
                new_team_admin.user,
                message=f"You are now the admin of the team {new_team_admin.team.name}",
                url=reverse('team_management'),
                icon='users',
            )

        if keycloak_user_id:
            result = keycloak.delete_user(keycloak_user_id)
            if 'error' in result:
                # Raising out of the atomic block rolls the Django delete back
                raise AccountDeletionError(f"Keycloak: {result['error']} Nothing was deleted, please try again.")
        else:
            logger.warning("Deleted user %s had no Keycloak account linked; nothing to delete there.", user_pk)

        _transition(locked, PrivacyRequest.Status.APPROVED,
                    status=PrivacyRequest.Status.COMPLETED, resolved_at=timezone.now(), resolved_by=deleted_by)
        transaction.on_commit(lambda: async_task('accounts.tasks.send_account_deleted_email', locked.pk))

    privacy_request.refresh_from_db()


def _next_team_admin(profile):
    """The member who joined the team first, if profile is a team admin who has members. Else None."""
    if profile is None or profile.team_id is None or profile.team_role != Profile.Team_Role.ADMIN:
        return None
    return (
        Profile.objects.filter(team_id=profile.team_id).exclude(pk=profile.pk)
        .select_related('user', 'team')
        .order_by(F('team_joined_at').asc(nulls_last=True), 'user__date_joined')
        .first()
    )
