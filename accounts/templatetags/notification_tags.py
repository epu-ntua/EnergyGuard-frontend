from django import template
from django.utils import timezone
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def ago(value):
    """ "5 minutes ago", or "just now" under a minute, where timesince would say "0 minutes". """
    if not value:
        return ""
    if (timezone.now() - value).total_seconds() < 60:
        return "just now"
    return f"{timesince(value)} ago"
