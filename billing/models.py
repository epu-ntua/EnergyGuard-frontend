from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import models
from core.models import TimeStampedModel


# Create your models here.
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
        db_table = 'core_paymentmethod'
        verbose_name = 'Payment Method'
        verbose_name_plural = 'Payment Methods'
        unique_together = ('user', 'card_number')
        ordering = ['-created_at']