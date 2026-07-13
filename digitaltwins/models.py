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
