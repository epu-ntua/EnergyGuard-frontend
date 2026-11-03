from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import Notification

NOTIFICATIONS_PER_PAGE = 20


def _notifications_next_url(request):
    """Where to go back after a notifications POST: the posted page if it is ours, else the notifications page."""
    next_url = request.POST.get("next")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = reverse("notifications")
    return next_url


def _group_by_day(notifications):
    """Consecutive notifications of the same local day, labelled Today / Yesterday / the date."""
    today = timezone.localdate()
    days = []
    for notification in notifications:
        day = timezone.localdate(notification.created_at)
        if not days or days[-1]["date"] != day:
            if day == today:
                label = "Today"
            elif day == today - timedelta(days=1):
                label = "Yesterday"
            else:
                label = date_format(day, "F j, Y")
            days.append({"date": day, "label": label, "is_today": day == today, "notifications": []})
        days[-1]["notifications"].append(notification)
    return days


@login_required
def notifications_list(request):
    notifications = Notification.objects.filter(recipient=request.user)
    unread_count = notifications.filter(is_read=False).count()
    active_filter = "unread" if request.GET.get("filter") == "unread" else "all"
    if active_filter == "unread":
        notifications = notifications.filter(is_read=False)

    page_obj = Paginator(notifications, NOTIFICATIONS_PER_PAGE).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/notifications.html",
        {
            "page_obj": page_obj,
            "notification_days": _group_by_day(page_obj),
            # Up to 7 buttons with "…", like DataTables' simple_numbers on the datasets list.
            "page_range": list(page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1)),
            "active_filter": active_filter,
            "unread_count": unread_count,
        },
    )


@login_required
def poll_notifications(request):
    unread = Notification.objects.filter(recipient=request.user, is_read=False)
    return JsonResponse({
        # Same window as the dropdown, so older unread ones are not toasted on every page load.
        "notifications": list(unread.values("id", "message", "icon", "created_at")[:Notification.DROPDOWN_LIMIT]),
        "count": unread.count(),
    })


@login_required
@require_POST
def read_notification(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    target = notification.url or reverse("notifications")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "url": target})
    return redirect(target)


@login_required
@require_POST
def mark_all_notifications_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect(_notifications_next_url(request))


@login_required
@require_POST
def set_notification_read(request, notification_id):
    """The per-row "Mark as read / unread" menu. Unlike read_notification, it stays on the page."""
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    is_read = request.POST.get("is_read")
    if is_read not in ("0", "1"):
        return HttpResponseBadRequest("is_read must be 0 or 1")
    notification.is_read = is_read == "1"
    notification.save(update_fields=["is_read"])
    return redirect(_notifications_next_url(request))
