from django.core.validators import MaxValueValidator
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel

# Create your models here.
class Experiment(TimeStampedModel):
    class ExpType(models.TextChoices):
        AI_MODEL = 'ai_model', 'AI Model'
        AI_SERVICE = 'ai_service', 'AI Service'
        WEB_APP = 'web_app', 'Web Application'
        MOBILE_APP = 'mobile_app', 'Mobile Application'
        IoT_INTEGRATION = 'iot_integration', 'IoT Integration'
        DATA_PIPELINE = 'data_pipeline', 'Data Pipeline'

    class Status(models.TextChoices):
        COMPLETED = "completed", "Completed"
        INACTIVE = "inactive", "Inactive"
        CANCELLED = "cancelled", "Cancelled"
        ONGOING = "ongoing", "Ongoing"
    
    name = models.CharField(max_length=255)
    collaborators = models.ManyToManyField(settings.AUTH_USER_MODEL, through='ExperimentCollaborator', related_name='collaborator_experiments')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_experiments')
    exp_type = models.CharField(max_length=20, choices= ExpType, default=ExpType.AI_MODEL)
    status = models.CharField(max_length=9, choices=Status, default=Status.INACTIVE)
    description = models.TextField(blank=True)
    visibility = models.BooleanField(default=False)
    # TODO: Implement dynamic progress calculation based on task completion
    # CURRENT: Static progress - FUTURE: Auto-calculated from experiment stages
    progress = models.PositiveBigIntegerField(default=0, validators=[MaxValueValidator(100)]) 

    def __str__(self):
        return self.name
    
    class Meta:
        db_table = 'experiment'
        verbose_name = 'Experiment'
        verbose_name_plural = 'Experiments'
        ordering = ["-created_at"]
        indexes = [models.Index(fields=['name']),]


# Intermediate model for collaborators - experiments with extra fields 
class ExperimentCollaborator(TimeStampedModel):
    class Permission(models.TextChoices):
        VIEW = 'view', 'Only View'
        EDIT = 'edit', 'Can Edit'

    collaborator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    experiment = models.ForeignKey(Experiment, on_delete=models.CASCADE)
    permission_level = models.CharField(max_length=4, choices=Permission, default=Permission.VIEW)

    class Meta:
        db_table = 'experiment_collaborator'
        verbose_name = 'Experiment Collaborator'
        verbose_name_plural = 'Experiment Collaborators'
        # Prevent multiple associations between the same instances
        constraints = [
            models.UniqueConstraint(
                fields=["collaborator", "experiment"], name="unique_person_experiment"
            )
        ]
