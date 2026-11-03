from django.contrib import admin

from .models import BerExperimentRequest, RdnSimulationJob


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


@admin.register(RdnSimulationJob)
class RdnSimulationJobAdmin(admin.ModelAdmin):
    """View-only: the qcluster poll chain owns status, result and error_message.

    error_message is the raw cause of a failure, which users never see - this is
    where to find it when someone reports a failed request by its number.
    """

    list_display = ('rdn_request_id', 'user', 'use_case', 'grid_section', 'status', 'created_at')
    list_filter = ('status', 'use_case', 'grid_section')
    list_select_related = ('user',)
    search_fields = ('=rdn_request_id', 'user__email')
    # The legacy inline result can be hundreds of megabytes.
    exclude = ('result',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
