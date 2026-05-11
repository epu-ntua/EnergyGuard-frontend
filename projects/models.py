from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class Project(TimeStampedModel):
    class ProjectType(models.TextChoices):
        AI_MODEL = 'ai_model', 'AI Model'
        AI_SERVICE = 'ai_service', 'AI Service'
        WEB_APP = 'web_app', 'Web Application'
        MOBILE_APP = 'mobile_app', 'Mobile Application'
        IOT_INTEGRATION = 'iot_integration', 'IoT Integration'
        DATA_PIPELINE = 'data_pipeline', 'Data Pipeline'

    name = models.CharField(max_length=255)
    collaborators = models.ManyToManyField(settings.AUTH_USER_MODEL, through='ProjectCollaborator', related_name='collaborator_projects')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_projects')
    team = models.ForeignKey('accounts.Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='projects')
    project_type = models.CharField(max_length=20, choices=ProjectType, default=ProjectType.AI_MODEL)
    description = models.TextField(blank=True)
    visibility = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Auto-assign to creator's team on creation; personal projects keep team=None
        if self._state.adding and self.team_id is None and self.creator_id:
            try:
                team = self.creator.profile.team
                if team is not None:
                    self.team = team
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

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
