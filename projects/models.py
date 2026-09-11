from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Project(TimeStampedModel):
    class ProjectType(models.TextChoices):
        AI_MODEL = 'ai_model', 'AI Model'
        AI_SERVICE = 'ai_service', 'AI Service'
        APPLICATION = 'application', 'Application'
        EDGE_EMBEDDED_AI = 'edge_embedded_ai', 'Edge / Embedded AI'
        DATA_PIPELINE = 'data_pipeline', 'Data Pipeline'
        SIMULATION_MODEL = 'simulation_model', 'Simulation Model'
        AI_AGENT_SYSTEM = 'ai_agent_system', 'AI Agent System'

    name = models.CharField(max_length=255)
    collaborators = models.ManyToManyField(settings.AUTH_USER_MODEL, through='ProjectCollaborator', related_name='collaborator_projects')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_projects')
    project_type = models.CharField(max_length=20, choices=ProjectType, default=ProjectType.AI_MODEL)
    description = models.TextField(blank=True)
    visibility = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def is_accessible_by(self, user):
        """READ access. A public project is readable by everyone.

        This must not be used to gate writes - see `can_edit`. Kept under its
        original name because other apps call it as a read check.
        """
        if self.visibility:
            return True
        if self.creator_id == user.id:
            return True
        return self.collaborators.filter(pk=user.pk).exists()

    # Alias that says what it actually means, for new call sites.
    can_view = is_accessible_by

    def can_edit(self, user):
        """WRITE access: the creator, or a collaborator granted EDIT.

        Public visibility deliberately grants nothing here - it makes a project
        readable, not writable. `ProjectCollaborator.permission_level` was
        declared but never enforced anywhere; this is where it takes effect.
        """
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if self.creator_id == user.id:
            return True
        return ProjectCollaborator.objects.filter(
            project=self, collaborator=user, permission_level=ProjectCollaborator.Permission.EDIT,
        ).exists()

    def can_delete(self, user):
        """Only the creator may delete a project or its experiments wholesale."""
        return bool(user and getattr(user, 'is_authenticated', False) and self.creator_id == user.id)

    class Meta:
        db_table = 'project'
        verbose_name = 'Project'
        verbose_name_plural = 'Projects'
        ordering = ["-created_at"]
        indexes = [models.Index(fields=['name']),]


class Experiment(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="experiments")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_experiments",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    mlflow_experiment_id = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name or f"Experiment {self.pk}"

    class Meta:
        db_table = "experiment"
        verbose_name = "Experiment"
        verbose_name_plural = "Experiments"
        ordering = ["-created_at"]


# Intermediate model for collaborators - projects with extra fields
class ProjectCollaborator(TimeStampedModel):
    class Permission(models.TextChoices):
        VIEW = 'view', 'Only View'
        EDIT = 'edit', 'Can Edit'

    collaborator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    permission_level = models.CharField(max_length=4, choices=Permission, default=Permission.VIEW)

    class Meta:
        db_table = 'project_collaborator'
        verbose_name = 'Project Collaborator'
        verbose_name_plural = 'Project Collaborators'
        # Prevent multiple associations between the same instances
        constraints = [
            models.UniqueConstraint(
                fields=["collaborator", "project"], name="unique_person_project"
            )
        ]
