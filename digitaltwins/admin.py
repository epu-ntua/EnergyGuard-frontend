from django.contrib import admin

from .models import BerExperimentRequest


@admin.register(BerExperimentRequest)
class BerExperimentRequestAdmin(admin.ModelAdmin):
    list_display = ('pk', 'user', 'status', 'created_at')
    list_filter = ('status',)
    list_editable = ('status',)
    readonly_fields = ('user', 'experiment_json', 'created_at', 'updated_at')
