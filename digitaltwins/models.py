from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class DtExport(TimeStampedModel):
    """A copy of a twin's result placed in the datasets bucket for JupyterHub.

    One row per export: the data-management server provisions files into JupyterHub
    only from the datasets bucket, so the result is copied there from where the
    twin keeps it. `source_key` is that original object (a DtRun's, an RDN job's or
    a BER request's result), so opening the same result again reuses this copy.
    Rows from before source_key existed hold JSON the browser sent and have none.
    """

    twin_slug = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bucket_name = models.CharField(max_length=100, default='')
    result_key = models.CharField(max_length=1024)
    source_key = models.CharField(max_length=1024, blank=True, default='', db_index=True)

    class Meta:
        # Named DtResult until it became only the record of an export; the table kept its name.
        db_table = 'dt_result'
        verbose_name = 'DT Export'
        verbose_name_plural = 'DT Exports'


class DtRun(TimeStampedModel):
    """One run of a twin that answers straight away (CIEMAT, Engreen).

    Written by the twin's own view when its service answers, so the history holds
    what the service returned and not what a browser later sends back. RDN and BER
    keep their own models: their runs are long-lived requests with another lifecycle.
    """

    class Status(models.TextChoices):
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'                # the twin's service returned an error
        NOT_KEPT = 'not_kept', 'Not kept'          # a result came back but was not stored

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='dt_runs')
    twin_slug = models.CharField(max_length=100)
    # What was run, within the twin, e.g. 'forecast' or 'compare' for CIEMAT.
    operation = models.CharField(max_length=50)
    # The validated parameters the service was called with.
    inputs = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    # Gzipped JSON in OBJECT_STORAGE_BUCKET_SIMULATIONS; empty unless COMPLETED.
    result_key = models.CharField(max_length=1024, blank=True, default='')
    # Runs are kept until the user deletes one; there is no soft delete, since they
    # can be re-run in seconds, so deleting removes the row and its stored result.
    error_message = models.TextField(blank=True, default='')

    @property
    def has_result(self):
        return bool(self.result_key)

    class Meta:
        db_table = 'dt_run'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'twin_slug', '-created_at'])]
        verbose_name = 'DT Run'
        verbose_name_plural = 'DT Runs'


class BerExperimentRequest(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'  # withdrawn by the requester while still pending

    # Terminal states: nothing more will happen to the request.
    FINISHED_STATUSES = (Status.COMPLETED, Status.REJECTED, Status.CANCELLED)

    user =models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ber_experiment_requests')
    experiment_json = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Set by BER staff when marking a request completed - the actual execution window,
    # distinct from created_at/updated_at which only track the request row itself.
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    # Object-storage key of the result file BER uploads when marking completed.
    # Explicit per-request upload, not timestamp-based retrieval from the Data Lake.
    result_key = models.CharField(max_length=1024, blank=True, default='')
    rejection_reason = models.TextField(blank=True, default='')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Two independent soft deletes, so neither side's cleanup changes what the other
    # sees. Both apply only to finished requests: a pending one must be decided by
    # BER or cancelled by the requester first, so nobody is left waiting on it.
    # - archived_*: BER staff hid it from the management list.
    # - hidden_by_user_at: the requester removed it from their own request list.
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    hidden_by_user_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'ber_experiment_request'
        ordering = ['-created_at']
        verbose_name = 'BER Experiment Request'
        verbose_name_plural = 'BER Experiment Requests'
        permissions = [
            ('manage_ber_requests', 'Can manage BER experiment requests'),
        ]


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
    # Object-storage key for the completed result. RDN payloads are bounded only
    # by the request validator's 4,000,000-sample ceiling, which is far too large
    # for a JSONB column - see digitaltwins/rdn/services/results.py.
    result_key = models.CharField(max_length=1024, blank=True, default='')
    # Legacy inline payload. Jobs that completed before results moved to object
    # storage still carry it; nothing new is written here unless the upload fails.
    result = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    @property
    def has_result(self):
        return bool(self.result_key) or self.result is not None

    class Meta:
        db_table = 'rdn_simulation_job'
        ordering = ['-created_at']
        verbose_name = 'RDN Simulation Job'
        verbose_name_plural = 'RDN Simulation Jobs'
