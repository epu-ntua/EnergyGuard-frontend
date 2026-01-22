from django.shortcuts import render
from .models import Billing
from django.db.models.aggregates import Sum

# Create your views here.

def currency_format(value):
    if value == Billing.Currency.USD:
        return "$"
    elif value == Billing.Currency.GBP:
        return "£"
    elif value == Billing.Currency.EUR:
        return "€"

def billing(request):
    # active_user = request.user
    # for i in range(1, 501):
    #     customer_billing = Billing.objects.filter(customer=i)
    #     if customer_billing.exists():
    #         # billing_info = customer_billing.latest('billing_period_end')
    #         for u in customer_billing:
    #             u.currency = customer_billing[0].currency
    #             u.save()
            # currency = currency_format(billing_info.currency)
    customer_billing_info = Billing.objects.filter(customer=23)  # Replace with active_user.id in production
    if customer_billing_info.exists():
        currency = currency_format(customer_billing_info[0].currency)
        total_cost = customer_billing_info.aggregate(Sum('amount')) or 0 # Sum of all amounts for this customer
        total_cost_amount = float(total_cost["amount__sum"]) if total_cost["amount__sum"] else 0.0
    else:
        currency = "€"
        total_cost_amount = 0.0
    return render(request, 'billing/billing.html', {"user": customer_billing_info, "active_navbar_page": "billing", "show_sidebar": True, "currency_format": currency, "sum": total_cost_amount})
