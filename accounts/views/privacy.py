import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import PrivacyRequest
from ..services.data_export import build_user_data_export
from ..services.privacy_requests import cancel_privacy_request, submit_privacy_request

logger = logging.getLogger(__name__)


def _privacy_tab_url():
    return f"{reverse('profile')}?tab=privacy"


@login_required
@require_POST
def create_privacy_request(request):
    kind = request.POST.get('kind')
    if kind not in PrivacyRequest.Kind.values:
        messages.error(request, "Unknown privacy request.")
        return redirect(_privacy_tab_url())

    privacy_request, created = submit_privacy_request(request, kind, request.POST.get('message', '')[:2000])
    label = privacy_request.get_kind_display().lower()
    if created:
        messages.success(request, f"Your request for a {label} has been sent. We will reply to {privacy_request.email}.")
    else:
        messages.info(request, f"You already have a pending request for a {label}.")
    return redirect(_privacy_tab_url())


@login_required
@require_POST
def cancel_privacy_request_view(request, request_id):
    if cancel_privacy_request(request.user, request_id):
        messages.success(request, "Your privacy request has been cancelled.")
    else:
        messages.error(request, "This request can no longer be cancelled.")
    return redirect(_privacy_tab_url())


@login_required
def download_personal_data(request):
    try:
        archive = build_user_data_export(request.user)
    except Exception:
        logger.exception("Personal data export failed for user %s", request.user.pk)
        messages.error(request, "We could not prepare your data right now. Please try again later.")
        return redirect(_privacy_tab_url())

    response = HttpResponse(archive, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="energyguard-personal-data-{timezone.now():%Y-%m-%d}.zip"'
    return response
