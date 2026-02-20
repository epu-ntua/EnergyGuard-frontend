from django.core.validators import MinValueValidator
from django.conf import settings
from django.db import models
from decimal import Decimal
from projects.models import Project
from core.models import TimeStampedModel

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

    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        PRIVATE = "private", "Private"
        RESTRICTED = "restricted", "Restricted"
        UNDER_REVIEW = "under_review", "Under Review"
        # APPROVED = "approved", "Approved"
        # REJECTED = "rejected", "Rejected"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    label = models.CharField(max_length=30, choices=Label, default=Label.RENEWABLE_ENERGY)
    source = models.CharField(max_length=20, choices=Source, default=Source.ENERGYGUARD_DL)
    status = models.CharField(max_length=20, choices=Status, default=Status.PRIVATE)
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
    # MinIO object key for optional metadata file.
    metadata_file = models.CharField(max_length=1024, blank=True, default='')
    bucket_name = models.CharField(max_length=63, default='energyguard-datasets')
    metadata = models.JSONField(blank=True, null=True)
    projects = models.ManyToManyField(Project, blank=True, related_name='datasets') # Projects that have used this dataset

    def __str__(self):
        return self.name

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
        indexes = [models.Index(fields=['name']),]

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
