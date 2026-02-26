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
    project_type = models.CharField(max_length=20, choices=ProjectType, default=ProjectType.AI_MODEL)
    description = models.TextField(blank=True)
    visibility = models.BooleanField(default=False)

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
    # Tags are stored only in local DB.
    tags = models.JSONField(blank=True, default=dict)
    mlflow_experiment_id = models.CharField(max_length=64, blank=True, default="")

    def _get_mlflow_experiment(self) -> dict:
        if not self.mlflow_experiment_id:
            return {}
        cached = getattr(self, "_mlflow_experiment_cache", None)
        if cached is not None:
            return cached
        try:
            from .services.mlflow_client import MlflowClientError, get_experiment

            cached = get_experiment(self.mlflow_experiment_id, user=self.creator)
        except (MlflowClientError, Exception):
            cached = {}
        self._mlflow_experiment_cache = cached
        return cached

    @property
    def name(self) -> str:
        experiment = self._get_mlflow_experiment()
        return str(experiment.get("name") or f"Experiment {self.pk}")

    @property
    def description(self) -> str:
        experiment = self._get_mlflow_experiment()
        return str(experiment.get("description") or "")

    def __str__(self):
        return self.name

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
