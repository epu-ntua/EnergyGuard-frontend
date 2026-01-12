from django.contrib import admin
from .models import Dataset, DatasetUserDownload

# Register your models here.
admin.site.register(Dataset)
admin.site.register(DatasetUserDownload)