from django.core.validators import MinValueValidator
from django.conf import settings
from django.db import models
from django.db.models import Q
from decimal import Decimal
from projects.models import Project
from core.models import TimeStampedModel


REVIEW_PERMISSION = 'datasets.review_dataset'


# The review rules, as queries. Dataset.is_published / is_awaiting_review are
# the same rules on a loaded instance - change them together.

def _submitted_q():
    """A user's dataset its publisher made public: the only kind reviewed.
    Platform-owned (publisher-less) data is curated by us and skips review."""
    return Q(visibility=True, publisher__isnull=False)


def _published_q():
    """Public and cleared for the catalogue."""
    return Q(visibility=True, publisher__isnull=True) | (_submitted_q() & Q(status=Dataset.Status.APPROVED))


class DatasetQuerySet(models.QuerySet):
    def published(self):
        """What the "Public" catalogue lists to everyone."""
        return self.filter(_published_q())

    def submitted_for_review(self):
        """Everything a reviewer has to decide or has decided."""
        return self.filter(_submitted_q())

    def awaiting_review(self):
        """Submitted, not yet decided."""
        return self.filter(_submitted_q(), status=Dataset.Status.UNDER_REVIEW)

    def visible_to(self, user):
        """Datasets `user` is allowed to see: published ones, plus their own.
        Reviewers also see every dataset submitted for publication.

        Every view that resolves a Dataset from a user-supplied id must go
        through this (or `Dataset.is_accessible_by`) - ids are sequential, so a
        bare `get_object_or_404(Dataset, pk=...)` is an enumeration hole.
        """
        if not user or not getattr(user, 'is_authenticated', False):
            return self.filter(_published_q())
        if user.is_staff:
            return self
        q = _published_q() | Q(publisher=user)
        if user.has_perm(REVIEW_PERMISSION):
            q |= _submitted_q()
        return self.filter(q)


# Create your models here.
class Dataset(TimeStampedModel):
    PLATFORM_PUBLISHER = "EnergyGuard"

    class Label(models.TextChoices):
        BUILDINGS_ENERGY_EFFICIENCY = "buildings_energy_efficiency", "Buildings & Energy Efficiency"
        SMART_GRIDS_MICROGRIDS = "smart_grids_microgrids", "Smart Grids & Microgrids"
        RENEWABLE_ENERGY = "renewable_energy", "Renewable Energy"
        ENERGY_STORAGE_BATTERIES = "energy_storage_batteries", "Energy Storage & Batteries"
        ELECTRIC_VEHICLES_CHARGING = "electric_vehicles_charging", "Electric Vehicles & Charging"
        CLIMATE_WEATHER_DATA = "climate_weather_data", "Climate & Weather Data"
        ENERGY_MARKETS_PRICING = "energy_markets_pricing", "Energy Markets & Pricing"
        IOT_SENSORS_MONITORING = "iot_sensors_monitoring", "IoT Sensors & Monitoring"
        GRID_STABILITY_ANOMALIES = "grid_stability_anomalies", "Grid Stability & Anomalies"
        HYBRID_CROSS_SECTOR = "hybrid_cross_sector", "Hybrid / Cross-sector datasets"

    class Source(models.TextChoices):
        ENERGYGUARD_DL = "energyguard_DL", "EnergyGuard Data Lake"
        DS = "DS", "Data Space"
        AI4EU = "ai4eu", "AI4EU Platform"
        EUROPEAN_DATA_PORTAL = "european_data_portal", "European Data Portal"
        OWN_DS = "your_own_DS", "Your Own Data Space"
        RIGA_ENERGY_AGENCY = "riga_energy_agency", "RIGA Energy Agency"

    class Status(models.TextChoices):
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    # Unique per publisher, not globally: a platform-wide unique name meant a
    # second partner picking "consumption-2025" only found out after their
    # multi-GB upload had already transferred (the row is created in the
    # background task, long after the wizard validated).
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    label = models.CharField(max_length=30, choices=Label, default=Label.RENEWABLE_ENERGY)
    source = models.CharField(max_length=20, choices=Source, default=Source.ENERGYGUARD_DL)
    # Only meaningful while visibility is on: a public dataset is listed once a
    # reviewer approves it. Private datasets are never reviewed.
    status = models.CharField(max_length=20, choices=Status, default=Status.UNDER_REVIEW)
    # db_default too: a process still running the previous code inserts rows
    # without this column (seen in the window between migrate and restart).
    rejection_reason = models.TextField(blank=True, default='', db_default='')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_datasets',
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    # When the publisher asked for publication (or re-review after an edit);
    # the review queue is ordered by it.
    submitted_at = models.DateTimeField(blank=True, null=True)
    visibility = models.BooleanField(default=False)
    size_gb = models.DecimalField(decimal_places=2, max_digits=12, validators=[MinValueValidator(Decimal('0.01'))])
    publisher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='published_datasets',
    )
    # MinIO object key for the primary dataset file.
    data_file = models.CharField(max_length=1024, blank=True, default='')
    bucket_name = models.CharField(max_length=63, default='energyguard-datasets')
    metadata = models.JSONField(blank=True, null=True)
    projects = models.ManyToManyField(Project, blank=True, related_name='datasets') # Projects that have used this dataset

    objects = DatasetQuerySet.as_manager()

    def __str__(self):
        return self.name

    @property
    def is_submitted_for_review(self) -> bool:
        """Mirrors _submitted_q()."""
        return self.visibility and self.publisher_id is not None

    @property
    def is_published(self) -> bool:
        """Mirrors _published_q()."""
        if not self.visibility:
            return False
        return self.publisher_id is None or self.status == self.Status.APPROVED

    @property
    def is_awaiting_review(self) -> bool:
        """Mirrors DatasetQuerySet.awaiting_review()."""
        return self.is_submitted_for_review and self.status == self.Status.UNDER_REVIEW

    def is_accessible_by(self, user) -> bool:
        """Read access. Mirrors DatasetQuerySet.visible_to()."""
        if self.is_published:
            return True
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_staff or self.publisher_id == user.id:
            return True
        return self.is_submitted_for_review and user.has_perm(REVIEW_PERMISSION)

    def is_editable_by(self, user) -> bool:
        """Write access - strictly the publisher. Public visibility never grants it."""
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return self.publisher_id is not None and self.publisher_id == user.id

    @property
    def pilot_partner(self) -> str | None:
        """
        The pilot partner this dataset belongs to, or None for a user-uploaded
        dataset. Pilot data is a platform-owned export shared by every user, so
        JupyterHub mounts it read-only instead of copying it per user.
        """
        from .services.pilot import pilot_partner_for

        return pilot_partner_for(self)

    @property
    def is_pilot(self) -> bool:
        return self.pilot_partner is not None

    @property
    def publisher_display(self) -> str:
        if self.publisher_id:
            full_name = self.publisher.get_full_name().strip()
            return full_name or self.publisher.get_username()
        return self.PLATFORM_PUBLISHER

    class Meta:
        db_table = 'dataset'
        verbose_name = 'Dataset'
        verbose_name_plural = 'Datasets'
        ordering = ['-created_at']
        indexes = []
        permissions = [
            ('review_dataset', 'Can approve or reject datasets submitted for publication'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['publisher', 'name'],
                name='unique_dataset_name_per_publisher',
            ),
            # publisher IS NULL is platform-owned data; NULLs do not collide under a
            # plain unique constraint, so those need their own partial index.
            models.UniqueConstraint(
                fields=['name'],
                condition=models.Q(publisher__isnull=True),
                name='unique_platform_dataset_name',
            ),
        ]

class DatasetUserDownload(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)

    class Meta:
        db_table = 'dataset_user_download'
        verbose_name = 'Dataset User Download'
        verbose_name_plural = 'Dataset User Downloads'
        constraints = [
            models.UniqueConstraint(fields=['user', 'dataset'], name='unique_user_dataset_download')
        ]
