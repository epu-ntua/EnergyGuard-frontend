import re

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path

from .models import PreapprovedEmail, PrivacyRequest, Profile, User
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


class PreapprovedEmailBulkForm(forms.Form):
    emails = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 15, 'cols': 60}),
        help_text='One per line, or separated by commas, semicolons or spaces.',
    )
    note = forms.CharField(max_length=255, required=False, help_text='Stored on every email added, e.g. "Beta testers, November 2026".')

    def clean_emails(self):
        emails = {e.lower() for e in re.split(r'[\s,;]+', self.cleaned_data['emails']) if e}
        invalid = []
        for email in sorted(emails):
            try:
                validate_email(email)
            except ValidationError:
                invalid.append(email)
        if invalid:
            raise ValidationError(f'Not valid emails, nothing was added: {", ".join(invalid)}')
        return sorted(emails)


@admin.register(PreapprovedEmail)
class PreapprovedEmailAdmin(admin.ModelAdmin):
    list_display = ('email', 'note', 'added_by', 'created_at', 'registered')
    search_fields = ('email', 'note')
    readonly_fields = ('added_by', 'created_at', 'updated_at')
    fields = ('email', 'note', 'added_by', 'created_at', 'updated_at')
    change_list_template = 'admin/accounts/preapprovedemail/change_list.html'

    @admin.display(boolean=True, description='Registered')
    def registered(self, obj):
        return User.objects.filter(email__iexact=obj.email).exists()

    def save_model(self, request, obj, form, change):
        if not change:
            obj.added_by = request.user
        super().save_model(request, obj, form, change)

    def get_urls(self):
        return [
            path('add-several/', self.admin_site.admin_view(self.add_several_view), name='accounts_preapprovedemail_add_several'),
        ] + super().get_urls()

    def add_several_view(self, request):
        if not self.has_add_permission(request):
            return redirect('admin:index')
        form = PreapprovedEmailBulkForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            emails = form.cleaned_data['emails']
            existing = set(PreapprovedEmail.objects.filter(email__in=emails).values_list('email', flat=True))
            new = [e for e in emails if e not in existing]
            PreapprovedEmail.objects.bulk_create(
                PreapprovedEmail(email=e, note=form.cleaned_data['note'], added_by=request.user) for e in new
            )
            message = f'{len(new)} email(s) added.'
            if existing:
                message += f' {len(existing)} already on the list.'
            self.message_user(request, message)
            return redirect('admin:accounts_preapprovedemail_changelist')
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Add several pre-approved emails',
            'form': form,
        }
        return TemplateResponse(request, 'admin/accounts/preapprovedemail/add_several.html', context)
