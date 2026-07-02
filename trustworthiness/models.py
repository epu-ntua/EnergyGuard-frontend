from django.db import models


class Assessment(models.Model):
    class AssessmentType(models.TextChoices):
        AI_ACT = 'ai_act', 'AI Act Questionnaire'
        CODE_ANALYSIS = 'code_analysis', 'Code Analysis'
        ROBUSTNESS = 'robustness', 'Adversarial Robustness'

    class Status(models.TextChoices):
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    project = models.ForeignKey(
        'experiments.Project',
        on_delete=models.CASCADE,
        related_name='assessments',
    )
    assessment_type = models.CharField(max_length=50, choices=AssessmentType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    input_data = models.JSONField(null=True, blank=True)
    results = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)
    parent_assessment = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='child_versions',
    )

    class Meta:
        db_table = 'assessments'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_assessment_type_display()} — {self.project} ({self.created_at:%Y-%m-%d %H:%M})"
