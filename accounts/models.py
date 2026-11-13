from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.dispatch import receiver
from django.conf import settings
import os, uuid

from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.utils import timezone

from core.models import TimeStampedModel

# Create your models here.

class UserManager(BaseUserManager):
    """
    Custom user model manager where email is the unique identifiers
    for authentication instead of usernames.
    """
    def create_user(self, email, password, **extra_fields):
        """
        Create and save a User with the given email and password.
        """
        if not email:
            raise ValueError(_('The Email must be set'))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.username = email
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password, **extra_fields):
        """
        Create and save a SuperUser with the given email and password.
        """
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))
        return self.create_user(email, password, **extra_fields)


# User extends AbstractUser 
class User(AbstractUser):

    class Membership(models.TextChoices):
        FREE = 'free', 'Free'
        PAID = 'paid', 'Paid'

    email = models.EmailField(unique=True)
    updated_at = models.DateTimeField(auto_now = True)
    membership = models.CharField(max_length=4, choices=Membership, default=Membership.FREE)
    credits = models.PositiveIntegerField(default=0)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  

    def save(self, *args, **kwargs):
        if self.first_name:
            self.first_name = self.first_name.strip().capitalize()
        if self.last_name:
            self.last_name = self.last_name.strip().capitalize()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    class Meta:
        db_table = 'core_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['last_name', 'first_name']
        indexes = [models.Index(fields=['email']),] # Index on email for faster lookups

class Profile(models.Model):

    class Team_Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        MEMBER = 'member', 'Member'

    # Solves hashing issues. Unique filename generator for profile pictures to avoid conflicts and ensure privacy. Format: profile_pics/{user_id}_{uuid4}.{ext}
    def profile_pic_upload_to(instance, filename):
            ext = os.path.splitext(filename)[1].lower()     # Get file extension   
            return f"profile_pics/{instance.user.id}_{uuid.uuid4().hex}{ext}"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    position = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    # Using ImageField for profile pictures. Requires Pillow library. Stored in MEDIA_ROOT/profile_pics/ with unique filenames to prevent conflicts.
    profile_picture = models.ImageField(upload_to=profile_pic_upload_to, null=True, blank=True)
    team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    team_role = models.CharField(max_length=10, choices=Team_Role.choices, default=None, null=True, blank=True)
    team_joined_at = models.DateTimeField(null=True, blank=True)
   
    # Display user-friendly validation messages
    def clean(self):
        super().clean()

        if not self.team:
            if self.team_role in [self.Team_Role.ADMIN, self.Team_Role.MEMBER]:
                raise ValidationError({"team_role": "A user cannot be an admin or member if they are not part of a team."})
            return
        
        if self.pk:
            old_profile = Profile.objects.get(pk=self.pk)
            if old_profile.team and old_profile.team != self.team:
                raise ValidationError({"team": "Cannot change team for a user of another team. Remove them from the current team before assigning them to a new team."})

    def __str__(self):
        return f"{self.user.last_name}, {self.user.first_name}'s Profile"
    
    class Meta:
        db_table = 'profile'
        verbose_name = 'Profile'
        verbose_name_plural = 'Profiles'
        ordering = ['user__last_name', 'user__first_name']
        indexes = [models.Index(fields=['user']),]  # Index on user for faster lookups
        constraints = [
            models.UniqueConstraint(fields=['team'], condition=Q(team_role='admin'), name='unique_team_admin'),
            models.CheckConstraint(
                condition=
                    Q(team__isnull=True, team_role__isnull=True) |
                    Q(team__isnull=False, team_role__isnull=False),
                name='team_and_role_together_or_both_null'
            ),  
        ]

# Custom manager for Team to handle team creation and assign admin role to creator
class TeamManager(models.Manager):
    @transaction.atomic
    def create_team_assign_admin(self, creator, name, description=""):
        profile, _ = Profile.objects.get_or_create(user=creator)

        if profile.team is not None:
            raise ValidationError("User is already part of a team.")

        # Create team and update creator's profile to assign them to the new team and set role to admin
        from django.utils import timezone
        team = self.create(name=name, description=description)
        profile.team = team
        profile.team_role = Profile.Team_Role.ADMIN
        profile.team_joined_at = timezone.now()
        profile.save()

        return team
    
class Team(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    
    objects = TeamManager()

    def __str__(self):
        return self.name
    
    class Meta:
        db_table = 'team'
        verbose_name = 'Team'
        verbose_name_plural = 'Teams'
        ordering = ['name']
        indexes = [models.Index(fields=['name']),]  # Index on name for faster lookups

class TeamInvite(models.Model):
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField()
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_invites')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    declined_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_accepted(self):
        return self.accepted_at is not None

    @property
    def is_declined(self):
        return self.declined_at is not None

    def __str__(self):
        return f"Invite to {self.email} for {self.team}"

    class Meta:
        db_table = 'team_invite'
        verbose_name = 'Team Invite'
        verbose_name_plural = 'Team Invites'


class Notification(models.Model):
    # The bell dropdown (and its poll) shows only the latest unread; the full history is on the notifications page.
    DROPDOWN_LIMIT = 5

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=255)
    url = models.CharField(max_length=500, blank=True)
    icon = models.CharField(max_length=50, default='bell')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['recipient', 'is_read'])]  # matches the poll/header query filter

    def __str__(self):
        return f"Notification for {self.recipient}: {self.message}"


class PrivacyRequest(TimeStampedModel):
    """A user's GDPR request, handled by an admin. Data export is self-service (services/data_export.py).

    Deletion: pending -> approved (the account is deleted on scheduled_for, which
    gives the user time to download their data) -> completed once an admin deletes
    the account. The user can cancel while it is pending or approved.
    """

    class Kind(models.TextChoices):
        DELETION = 'deletion', 'Deletion of personal data'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        COMPLETED = 'completed', 'Completed'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

    OPEN_STATUSES = (Status.PENDING, Status.APPROVED)

    # SET_NULL + email snapshot: the request record must outlive a completed deletion
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='privacy_requests')
    email = models.EmailField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    message = models.TextField(blank=True)
    admin_note = models.TextField(blank=True, help_text='Shown to the user and included in the email sent on approval or rejection.')
    scheduled_for = models.DateField(null=True, blank=True, help_text='Day the account is deleted. Set on approval.')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_due(self):
        """Approved and its deletion day has come."""
        return self.status == self.Status.APPROVED and self.scheduled_for is not None and self.scheduled_for <= timezone.localdate()

    def __str__(self):
        return f"{self.get_kind_display()} request by {self.email} ({self.status})"

    class Meta:
        db_table = 'privacy_request'
        verbose_name = 'Privacy Request'
        verbose_name_plural = 'Privacy Requests'
        ordering = ['-created_at']
        constraints = [
            # One open request per kind per user, so double submits don't pile up
            models.UniqueConstraint(fields=['user', 'kind'], condition=Q(status__in=['pending', 'approved']), name='unique_open_privacy_request'),
        ]


class PreapprovedEmail(TimeStampedModel):
    """An email whose new account skips admin approval (e.g. invited beta testers).

    Only applies when Keycloak reports the email as verified, see accounts/adapter.py.
    """

    email = models.EmailField(unique=True)
    note = models.CharField(max_length=255, blank=True, help_text='e.g. "Beta testers, November 2026"')
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def clean(self):
        # Before the admin form's uniqueness check, so A@x.com is caught as a duplicate of a@x.com
        self.email = self.email.strip().lower()

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @classmethod
    def covers(cls, email):
        # iexact: rows written without save() (bulk_create, update) are not normalised
        return bool(email) and cls.objects.filter(email__iexact=email.strip()).exists()

    def __str__(self):
        return self.email

    class Meta:
        db_table = 'preapproved_email'
        verbose_name = 'Pre-approved Email'
        verbose_name_plural = 'Pre-approved Emails'
        ordering = ['email']


# ------------------- SIGNALS ------------------- #

# Automatically create a Profile for each new User and save the Profile when the User is saved
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

        # Register the user in MLflow-OIDC so they can receive experiment permissions
        try:
            from projects.services.mlflow_client import create_mlflow_user
            display_name = f"{instance.first_name} {instance.last_name}".strip() or instance.email
            create_mlflow_user(instance.email, display_name=display_name)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to create MLflow user for %s", instance.email, exc_info=True
            )

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()