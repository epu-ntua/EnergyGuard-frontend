from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.mail import send_mail
from django.conf import settings

from .models import PrivacyRequest, Profile, User
from .services.privacy_requests import resolve_privacy_request


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


admin.site.register(Profile)


@admin.register(PrivacyRequest)
class PrivacyRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'kind', 'status', 'created_at', 'resolved_at', 'resolved_by')
    list_filter = ('status', 'kind')
    search_fields = ('email',)
    readonly_fields = ('user', 'email', 'kind', 'status', 'message', 'created_at', 'resolved_at', 'resolved_by')
    fields = ('user', 'email', 'kind', 'status', 'message', 'admin_note', 'created_at', 'resolved_at', 'resolved_by')
    actions = ['mark_completed', 'mark_rejected']

    def has_add_permission(self, request):
        return False

    def _resolve(self, request, queryset, status):
        count = sum(resolve_privacy_request(pr, status, request.user) for pr in queryset)
        self.message_user(request, f'{count} pending request(s) marked as {status}. The users have been notified.')

    @admin.action(description='Mark selected requests as completed')
    def mark_completed(self, request, queryset):
        self._resolve(request, queryset, PrivacyRequest.Status.COMPLETED)

    @admin.action(description='Mark selected requests as rejected')
    def mark_rejected(self, request, queryset):
        self._resolve(request, queryset, PrivacyRequest.Status.REJECTED)
