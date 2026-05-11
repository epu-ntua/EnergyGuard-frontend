import logging

from allauth.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.core.mail import mail_admins
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


class KeycloakApprovalAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing and not sociallogin.user.is_active:
            request.session['pending_approval'] = True
            request.session['pending_user_name'] = sociallogin.user.get_full_name() or sociallogin.user.email
            raise ImmediateHttpResponse(redirect('account_pending_approval'))

    def save_user(self, request, sociallogin, form=None):
        is_new = not sociallogin.user.pk
        user = super().save_user(request, sociallogin, form)
        if is_new:
            user.is_active = False
            user.save(update_fields=['is_active'])
            self._notify_admins(request, user)
            request.session['pending_approval'] = True
            request.session['pending_user_name'] = user.get_full_name() or user.email
            raise ImmediateHttpResponse(redirect('account_pending_approval'))
        return user

    def _notify_admins(self, request, user):
        try:
            admin_url = request.build_absolute_uri(
                f'/admin/accounts/user/{user.pk}/change/'
            )
            mail_admins(
                subject=f'[EnergyGuard] New user pending approval: {user.email}',
                message=(
                    f'A new user registered and is awaiting approval.\n\n'
                    f'Name: {user.get_full_name()}\n'
                    f'Email: {user.email}\n\n'
                    f'Approve here: {admin_url}'
                ),
            )
        except Exception:
            logger.exception('Failed to notify admins for new user %s', user.email)
