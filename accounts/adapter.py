import logging

from allauth.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.core.mail import mail_admins
from django.shortcuts import redirect

from .models import PreapprovedEmail

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
        if is_new and self._is_preapproved(sociallogin, user):
            self._notify_admins(request, user, preapproved=True)
        elif is_new:
            user.is_active = False
            user.save(update_fields=['is_active'])
            self._notify_admins(request, user)
            request.session['pending_approval'] = True
            request.session['pending_user_name'] = user.get_full_name() or user.email
            raise ImmediateHttpResponse(redirect('account_pending_approval'))
        return user

    def _is_preapproved(self, sociallogin, user):
        # Keycloak must have verified the email, or anyone could register with a listed address
        email = (user.email or '').lower()
        verified = any(a.verified and a.email.lower() == email for a in sociallogin.email_addresses)
        return verified and PreapprovedEmail.covers(email)

    def _notify_admins(self, request, user, preapproved=False):
        try:
            admin_url = request.build_absolute_uri(
                f'/admin/accounts/user/{user.pk}/change/'
            )
            if preapproved:
                subject = f'[EnergyGuard] New pre-approved user: {user.email}'
                intro = 'A new user on the pre-approved list registered and was activated automatically.'
                action = f'User: {admin_url}'
            else:
                subject = f'[EnergyGuard] New user pending approval: {user.email}'
                intro = 'A new user registered and is awaiting approval.'
                action = f'Approve here: {admin_url}'
            mail_admins(
                subject=subject,
                message=(
                    f'{intro}\n\n'
                    f'Name: {user.get_full_name()}\n'
                    f'Email: {user.email}\n\n'
                    f'{action}'
                ),
            )
        except Exception:
            logger.exception('Failed to notify admins for new user %s', user.email)
