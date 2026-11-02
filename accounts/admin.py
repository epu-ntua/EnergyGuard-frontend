from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.mail import send_mail
from django.conf import settings
from django.http import HttpResponseRedirect

from .models import PrivacyRequest, Profile, User
from .services.privacy_requests import (
    DELETION_GRACE_DAYS, AccountDeletionError, approve_privacy_request, delete_account, reject_privacy_request,
)


def _send_approval_email(request, user):
    login_url = request.build_absolute_uri('/accounts/keycloak-register/')
    send_mail(
        subject='[EnergyGuard] Your account has been approved',
        message=(
            f'Hello {user.get_full_name() or user.email},\n\n'
            f'Your EnergyGuard account has been approved. You can now sign in:\n'
            f'{login_url}\n\n'
            f'Welcome aboard!'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=True,
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_active', 'membership', 'date_joined')
    list_filter = ('is_active', 'membership', 'is_staff')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    actions = ['approve_users']

    @admin.action(description='Approve selected users')
    def approve_users(self, request, queryset):
        to_approve = list(queryset.filter(is_active=False))
        count = queryset.filter(is_active=False).update(is_active=True)
        for user in to_approve:
            _send_approval_email(request, user)
        self.message_user(request, f'{count} user(s) approved.')

    def save_model(self, request, obj, form, change):
        is_newly_approved = (
            change
            and 'is_active' in form.changed_data
            and obj.is_active
        )
        super().save_model(request, obj, form, change)
        if is_newly_approved:
            _send_approval_email(request, obj)

    # A user with an open privacy request is deleted from that request ("Delete account
    # now"), which also deletes them from Keycloak and closes the request.
    def _has_open_privacy_request(self, user):
        return user.privacy_requests.filter(status__in=PrivacyRequest.OPEN_STATUSES).exists()

    def has_delete_permission(self, request, obj=None):
        if obj is not None and self._has_open_privacy_request(obj):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        blocked = queryset.filter(privacy_requests__status__in=PrivacyRequest.OPEN_STATUSES).distinct()
        if blocked:
            self.message_user(
                request,
                f'Not deleted, they have an open privacy request: {", ".join(u.email for u in blocked)}. '
                f'Use "Delete account now" on the request instead.',
                messages.WARNING,
            )
            queryset = queryset.exclude(pk__in=blocked)
        super().delete_queryset(request, queryset)


admin.site.register(Profile)


@admin.register(PrivacyRequest)
class PrivacyRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'kind', 'status', 'scheduled_for', 'created_at', 'resolved_at', 'resolved_by')
    list_filter = ('status', 'kind')
    search_fields = ('email',)
    readonly_fields = ('user', 'email', 'kind', 'status', 'message', 'scheduled_for', 'created_at', 'resolved_at', 'resolved_by')
    fields = ('user', 'email', 'kind', 'status', 'message', 'admin_note', 'scheduled_for', 'created_at', 'resolved_at', 'resolved_by')
    # Approve / Reject / Delete account now buttons, see response_change
    change_form_template = 'admin/accounts/privacyrequest/change_form.html'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # The requests are the record of how each GDPR request was handled
        return False

    def save_model(self, request, obj, form, change):
        # Only the note: obj was loaded when the POST arrived, and writing its other
        # fields back would undo a cancel the user made in the meantime
        obj.save(update_fields=['admin_note', 'updated_at'])

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = {**(extra_context or {}), 'deletion_grace_days': DELETION_GRACE_DAYS}
        return super().change_view(request, object_id, form_url, extra_context)

    def response_change(self, request, obj):
        # The form, admin_note included, is saved by now, so the email the decision sends carries the note
        if '_approve' in request.POST:
            if approve_privacy_request(obj, request.user):
                self.message_user(request, f'Approved. {obj.email} has been notified; the account is due for deletion on {obj.scheduled_for:%d %b %Y}.')
            else:
                self.message_user(request, 'This request is no longer pending.', messages.WARNING)
        elif '_reject' in request.POST:
            if reject_privacy_request(obj, request.user):
                self.message_user(request, f'Rejected. {obj.email} has been notified.')
            else:
                self.message_user(request, 'This request is no longer pending.', messages.WARNING)
        elif '_delete_account' in request.POST:
            try:
                delete_account(obj, request.user)
            except AccountDeletionError as e:
                self.message_user(request, str(e), messages.ERROR)
            else:
                self.message_user(request, f'The account of {obj.email} has been deleted from EnergyGuard and Keycloak. The user has been emailed.')
        else:
            return super().response_change(request, obj)
        return HttpResponseRedirect(request.path)
