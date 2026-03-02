from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import TimeStampedModel
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

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

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    position = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    team_role = models.CharField(max_length=10, choices=Team_Role.choices, default=None, null=True, blank=True)
   
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
        team = self.create(name=name, description=description)
        profile.team = team
        profile.team_role = Profile.Team_Role.ADMIN
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

# ------------------- SIGNALS ------------------- #

# Automatically create a Profile for each new User and save the Profile when the User is saved
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()