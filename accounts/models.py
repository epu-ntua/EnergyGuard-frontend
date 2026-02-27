from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import TimeStampedModel
from django.core.exceptions import ValidationError

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

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    position = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)

    # If a user is a creator of a team, they cannot be a member of any team.
    def clean(self):
        super().clean()
        # Fixed registration flow issue: Profile gets validated before User is saved, so user_id can be None during validation. Skip validation in that case and rely on Team's clean() to catch any issues after User is created.
        if self.user_id is None:
            return
        created_team = getattr(self.user, "created_team", None)
        if self.team and created_team and created_team.pk != self.team_id:
            raise ValidationError("This user is a creator of a team and cannot be a member of another team.")
   
    def __str__(self):
        if self.user_id is None:
            return "Unassigned Profile"
        return f"{self.user.last_name}, {self.user.first_name}'s Profile"
    
    class Meta:
        db_table = 'profile'
        verbose_name = 'Profile'
        verbose_name_plural = 'Profiles'
        ordering = ['user__last_name', 'user__first_name']
        indexes = [models.Index(fields=['user']),]  # Index on user for faster lookups

class Team(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    
    # OneToOneField: 1 Team = 1 Creator & 1 User = Creator σε MAX 1 Team
    creator = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='created_team'
    )

    # If a user is a member of a team (through their profile), they cannot be a creator of any team.
    def clean(self):
        super().clean()
        if self.creator_id is None:
            return
        profile = getattr(self.creator, "profile", None)
        if profile and profile.team_id is not None and profile.team_id != self.pk:
            raise ValidationError("This user is already a member of a team and cannot be a creator of another team.")

    def __str__(self):
        return self.name
    
    class Meta:
        db_table = 'team'
        verbose_name = 'Team'
        verbose_name_plural = 'Teams'
        ordering = ['name']
        indexes = [models.Index(fields=['name']),]  # Index on name for faster lookups
