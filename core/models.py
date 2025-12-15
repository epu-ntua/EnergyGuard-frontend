from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator
from django.conf import settings
from django.core.exceptions import ValidationError

# User extends AbstractUser 
class User(AbstractUser):

    class Membership(models.TextChoices):
        FREE = 'free', 'Free'
        PAID = 'paid', 'Paid'

    email = models.EmailField(unique=True)
    updated_at = models.DateTimeField(auto_now = True)
    membership = models.CharField(max_length=4, choices=Membership, default=Membership.FREE)
    credits = models.PositiveIntegerField(default=0)

    USERNAME_FIELD = 'email' # Use email to log in
    REQUIRED_FIELDS = []  

    def __str__(self):
        return self.email
    
    class Meta:
        # db_table = 'user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['last_name', 'first_name']
        indexes = [models.Index(fields=['email']),] # Index on email for faster lookups

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    company = models.CharField(max_length=100, blank=True)
    position = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)

    def __str__(self):
        return f"{self.user.last_name}, {self.user.first_name}'s Profile"
    
    class Meta:
        db_table = 'profile'
        verbose_name = 'Profile'
        verbose_name_plural = 'Profiles'
        ordering = ['user__last_name', 'user__first_name']
        indexes = [models.Index(fields=['user']),]  # Index on user for faster lookups

# Abstract class for automatic time tracking - To be inherited
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True
    
# Experiment Table
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

# Dataset Table
class Dataset(TimeStampedModel):
    # class Label(models.TextChoices):
    #     BUILDINGS = "buildings", "Buildings"
    #     SMART_GRIDS = "smart_grids", "Smart Grids"
    #     RENEWABLE_ENERGY = "renewable_energy", "Renewable Energy"
    
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

    name = models.CharField(max_length=255)
    label = models.CharField(max_length=30, choices=Label, default=Label.RENEWABLE_ENERGY)
    source = models.CharField(max_length=20, choices=Source, default=Source.ENERGYGUARD_DL)
    status = models.CharField(max_length=20, choices=Status, default=Status.PRIVATE)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='dataset_list')
    experiments = models.ManyToManyField(Experiment, blank=True, related_name='datasets')
    visibility = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'dataset'
        verbose_name = 'Dataset'
        verbose_name_plural = 'Datasets'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['name']),]

# Billing Table
class Billing(TimeStampedModel):
    class PlanType(models.TextChoices):
        STANDARD = "standard", "Standard"
        TEAM = "team", "Team"
        BUSINESS = "business", "Business"
        ENTERPRISE = "enterprise", "Enterprise"

    # class PaymentMethod(models.TextChoices):
    #     CREDIT_CARD = "CC", "Credit Card"
    #     PAYPAL = "PP", "PayPal"
    #     BANK_TRANSFER = "BT", "Bank Transfer"

    class PaymentStatus(models.TextChoices):
        PAID = "paid", "Paid"
        PENDING = "pending", "Pending"
        NO_CHARGE = "no_charge", "No Charge"

    class Currency(models.TextChoices):
        EUR = "EUR", "Euros"
        USD = "USD", "Dollars"
        GBP = "GBP", "British Pound"
 
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    amount = models.DecimalField(max_digits=6, decimal_places=2)
    invoice = models.CharField(max_length=100, unique=True)
    plan_type = models.CharField(max_length=10, choices=PlanType, default=PlanType.BUSINESS)
    # payment_method = models.CharField(max_length=2, choices=PaymentMethod, default=PaymentMethod.CREDIT_CARD)
    payment_method_used = models.ForeignKey(
        'PaymentMethod',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='billings_used'
    )
    payment_status = models.CharField(max_length=9, choices=PaymentStatus, default=PaymentStatus.PENDING)
    currency = models.CharField(max_length=3, choices=Currency, default=Currency.EUR)

    def clean(self):
        if self.billing_period_end <= self.billing_period_start:
            raise ValidationError("Billing period end date must be after start date.")

    def __str__(self):
        return f"{self.customer.email} - {self.invoice}"

    class Meta:
        db_table = 'billing'
        verbose_name = 'Billing Record'
        verbose_name_plural = 'Billing Records'
        ordering = ['-billing_period_start']
        indexes = [models.Index(fields=['invoice']),]

class PaymentMethod(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_methods')
    
    # ID from the payment gateway (e.g., Stripe, PayPal)
    # gateway_payment_method_id = models.CharField(max_length=255, unique=True, help_text="ID for this specific payment method at the payment gateway")
    
    card_number = models.CharField(max_length=20, blank=True, null=True)
    cardholder_name = models.CharField(max_length=50, blank=True, null=True)
    cvv = models.CharField(max_length=3, blank=True, null=True)
    expiration_month = models.CharField(max_length=2, choices=[(str(i), str(i)) for i in range(1, 13)],  blank=True, null=True)
    expiration_year = models.CharField(max_length=2, blank=True, null=True)
    
    def __str__(self):
        return f"{self.user.email} - {self.cardholder_name} - **** **** **** {self.card_number[-4:]}"

    class Meta:
        verbose_name = 'Payment Method'
        verbose_name_plural = 'Payment Methods'
        unique_together = ('user', 'card_number')
        ordering = ['-created_at']