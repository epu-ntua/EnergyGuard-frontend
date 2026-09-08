from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class DtResult(TimeStampedModel):
    twin_slug = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bucket_name = models.CharField(max_length=100, default='')
    result_key = models.CharField(max_length=1024)

    class Meta:
        db_table = 'dt_result'
        verbose_name = 'DT Result'
        verbose_name_plural = 'DT Results'


class BerExperimentRequest(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        REJECTED = 'rejected', 'Rejected'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ber_experiment_requests')
    experiment_json = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        db_table = 'ber_experiment_request'
        ordering = ['-created_at']
        verbose_name = 'BER Experiment Request'
        verbose_name_plural = 'BER Experiment Requests'


class RdnSimulationJob(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='rdn_simulation_jobs')
    # Nullable because the row is created first (to obtain its pk), then rdn_request_id
    # is set to that pk and saved - see rdn_grid_simulate. Postgres allows multiple NULLs
    # under a unique constraint, so the brief pre-update state never collides.
    rdn_request_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    use_case = models.CharField(max_length=50)
    grid_section = models.CharField(max_length=10)
    # {asset_NNN: assetType} snapshot of the INPUT asset ids, for "continue previous
    # request" - RDN's output re-keys assets as grid_NNN, which is not a valid asset_NNN
    # id for a follow-up submission, so the original input-side mapping must be kept.
    assets = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'rdn_simulation_job'
        ordering = ['-created_at']
        verbose_name = 'RDN Simulation Job'
        verbose_name_plural = 'RDN Simulation Jobs'
