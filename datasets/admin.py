from django.contrib import admin
from .models import Dataset, DatasetUserDownload


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ('name', 'publisher', 'visibility', 'status', 'reviewed_by', 'reviewed_at', 'created_at')
    list_filter = ('status', 'visibility', 'label', 'source')
    search_fields = ('name', 'publisher__email')
    raw_id_fields = ('publisher', 'reviewed_by')


admin.site.register(DatasetUserDownload)
