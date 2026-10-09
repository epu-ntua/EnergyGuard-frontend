from django.contrib import admin

from .models import BerExperimentRequest


@admin.register(BerExperimentRequest)
class BerExperimentRequestAdmin(admin.ModelAdmin):
    list_display = ('pk', 'user', 'status', 'created_at', 'archived_at')
    list_filter = ('status', ('archived_at', admin.EmptyFieldListFilter))
    list_select_related = ('user',)
    # Status changes go through the BER management page, which enforces the allowed
    # transitions and notifies the requester - editing it here would bypass both.
    readonly_fields = (
        'user', 'experiment_json', 'status', 'actual_start', 'actual_end', 'result_key',
        'cancelled_at', 'archived_at', 'archived_by', 'hidden_by_user_at', 'created_at', 'updated_at',
    )
