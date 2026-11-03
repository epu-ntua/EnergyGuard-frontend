import json

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import User

# Django's ModelBackend.get_user() checks is_active and returns None for
# inactive users, so force_login(inactive_user) produces AnonymousUser on the
# next request before any middleware runs.  To test that our middleware catches
# an inactive-but-authenticated session, we use AllowAllUsersModelBackend
# which skips that check, simulating a custom backend without the guard.
_ALLOW_ALL_BACKENDS = [
    "django.contrib.auth.backends.AllowAllUsersModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]


class InactiveUserMiddlewareTests(TestCase):
    """
    KeycloakTokenExpiryMiddleware must immediately log out and redirect any
    authenticated session whose user.is_active is False.
    """

    def setUp(self):
        self.client = Client()
        self.active_user = User.objects.create_user(
            email="active@example.com", password="testpass123", is_active=True
        )
        self.inactive_user = User.objects.create_user(
            email="inactive@example.com", password="testpass123", is_active=False
        )

    def test_active_user_passes_through(self):
        self.client.force_login(self.active_user)
        response = self.client.get(reverse("home"))
        # Active user is redirected to dashboard, not kicked to login
        self.assertNotEqual(
            response.get("Location", ""), reverse("account_login")
        )

    @override_settings(AUTHENTICATION_BACKENDS=_ALLOW_ALL_BACKENDS)
    def test_inactive_user_is_logged_out_and_redirected(self):
        # AllowAllUsersModelBackend lets force_login work for inactive users
        self.client.force_login(
            self.inactive_user,
            backend="django.contrib.auth.backends.AllowAllUsersModelBackend",
        )
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    @override_settings(AUTHENTICATION_BACKENDS=_ALLOW_ALL_BACKENDS)
    def test_inactive_user_blocked_on_protected_view(self):
        self.client.force_login(
            self.inactive_user,
            backend="django.contrib.auth.backends.AllowAllUsersModelBackend",
        )
        response = self.client.get(reverse("dashboard"))
        # Must be a redirect (kicked out), not allowed in
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_deactivated_user_cannot_access_dashboard(self):
        """End-to-end: user was active, admin deactivates, next request blocked."""
        self.client.force_login(self.active_user)
        # Admin deactivates the user via DB (bypasses object cache)
        User.objects.filter(pk=self.active_user.pk).update(is_active=False)
        response = self.client.get(reverse("dashboard"))
        # Django's ModelBackend already handles this — session returns AnonymousUser
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.get("Location", ""), reverse("dashboard"))


class PendingApprovalViewTests(TestCase):
    """
    The pending_approval view must handle all four session states correctly.
    """

    def setUp(self):
        self.client = Client()
        self.active_user = User.objects.create_user(
            email="active@example.com", password="testpass123", is_active=True
        )
        self.inactive_user = User.objects.create_user(
            email="inactive@example.com", password="testpass123", is_active=False
        )
        self.url = reverse("account_pending_approval")

    def test_unauthenticated_with_pending_flag_sees_page(self):
        session = self.client.session
        session["pending_approval"] = True
        session["pending_user_name"] = "Test User"
        session.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_unauthenticated_without_pending_flag_redirects_home(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_active_authenticated_user_redirected_to_home(self):
        self.client.force_login(self.active_user)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    @override_settings(AUTHENTICATION_BACKENDS=_ALLOW_ALL_BACKENDS)
    def test_inactive_authenticated_user_is_logged_out_and_sent_to_login(self):
        self.client.force_login(
            self.inactive_user,
            backend="django.contrib.auth.backends.AllowAllUsersModelBackend",
        )
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


class PrivacyRequestTests(TestCase):

    def setUp(self):
        from unittest.mock import patch
        self.user = User.objects.create_user(email="gdpr@example.com", password="testpass123", is_active=True)
        self.other = User.objects.create_user(email="other@example.com", password="testpass123", is_active=True)
        self.client.force_login(self.user)
        patcher = patch("accounts.services.privacy_requests.async_task")
        self.async_task = patcher.start()
        self.addCleanup(patcher.stop)

    def _submit(self, kind, message=""):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("create_privacy_request"), {"kind": kind, "message": message})

    def test_submit_creates_pending_request_and_queues_emails(self):
        from accounts.models import PrivacyRequest
        response = self._submit("deletion", "please")
        self.assertRedirects(response, f"{reverse('profile')}?tab=privacy", fetch_redirect_response=False)
        pr = PrivacyRequest.objects.get(user=self.user)
        self.assertEqual((pr.kind, pr.status, pr.email, pr.message), ("deletion", "pending", self.user.email, "please"))
        self.assertEqual(self.async_task.call_args[0][0], "accounts.tasks.send_privacy_request_emails")

    def test_double_submit_is_idempotent(self):
        from accounts.models import PrivacyRequest
        self._submit("deletion")
        self._submit("deletion")
        self.assertEqual(PrivacyRequest.objects.filter(user=self.user, kind="deletion").count(), 1)
        self.assertEqual(self.async_task.call_count, 1)

    def test_unknown_kind_is_rejected(self):
        from accounts.models import PrivacyRequest
        self._submit("export")
        self.assertFalse(PrivacyRequest.objects.exists())

    def test_user_cannot_cancel_someone_elses_request(self):
        from accounts.models import PrivacyRequest
        pr = PrivacyRequest.objects.create(user=self.other, email=self.other.email, kind="deletion")
        self.client.post(reverse("cancel_privacy_request", args=[pr.pk]))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "pending")

    def test_user_can_cancel_own_pending_request(self):
        from accounts.models import PrivacyRequest
        pr = PrivacyRequest.objects.create(user=self.user, email=self.user.email, kind="deletion")
        self.client.post(reverse("cancel_privacy_request", args=[pr.pk]))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "cancelled")

    def test_approve_schedules_deletion_and_notifies_user_once(self):
        import datetime
        from django.utils import timezone
        from accounts.models import Notification, PrivacyRequest
        from accounts.services.privacy_requests import approve_privacy_request, reject_privacy_request
        pr = PrivacyRequest.objects.create(user=self.user, email=self.user.email, kind="deletion")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(approve_privacy_request(pr, self.other))
        self.assertFalse(approve_privacy_request(pr, self.other))
        self.assertFalse(reject_privacy_request(pr, self.other))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "approved")
        self.assertEqual(pr.scheduled_for, timezone.localdate() + datetime.timedelta(days=2))
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)
        self.assertEqual(self.async_task.call_args[0][0], "accounts.tasks.send_privacy_request_approved_email")

    def test_user_can_cancel_approved_request_and_admins_are_told(self):
        from accounts.models import PrivacyRequest
        pr = PrivacyRequest.objects.create(user=self.user, email=self.user.email, kind="deletion", status="approved")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("cancel_privacy_request", args=[pr.pk]))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "cancelled")
        self.assertEqual(self.async_task.call_args[0][0], "accounts.tasks.send_privacy_request_cancelled_email")

    def test_cannot_submit_while_a_request_is_approved(self):
        from accounts.models import PrivacyRequest
        PrivacyRequest.objects.create(user=self.user, email=self.user.email, kind="deletion", status="approved")
        self._submit("deletion")
        self.assertEqual(PrivacyRequest.objects.filter(user=self.user).count(), 1)
        self.async_task.assert_not_called()

    def test_profile_privacy_tab_renders(self):
        response = self.client.get(f"{reverse('profile')}?tab=privacy")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="tab-privacy"')
        self.assertContains(response, 'id="privacyDeletionModal"')


class PersonalDataExportTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(email="me@example.com", password="testpass123", is_active=True, first_name="ann")
        self.other = User.objects.create_user(email="someone@example.com", password="testpass123", is_active=True)
        self.client.force_login(self.user)

    def _download(self):
        import io, json, zipfile
        response = self.client.get(reverse("download_personal_data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("attachment;", response["Content-Disposition"])
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        return json.loads(archive.read("personal_data.json"))

    def test_export_contains_own_account_data(self):
        from projects.models import Project
        Project.objects.create(name="Mine", creator=self.user)
        Project.objects.create(name="Theirs", creator=self.other)
        data = self._download()
        self.assertEqual(data["account"]["email"], "me@example.com")
        self.assertEqual(data["account"]["first_name"], "Ann")
        self.assertEqual([p["name"] for p in data["projects_created"]], ["Mine"])

    def test_export_contains_own_digital_twin_runs(self):
        from digitaltwins.models import DtRun
        DtRun.objects.create(user=self.user, twin_slug="ciemat", operation="forecast", inputs={"days": 3}, status="completed")
        DtRun.objects.create(user=self.other, twin_slug="engreen", operation="run", status="failed")
        data = self._download()
        self.assertEqual([(r["twin_slug"], r["inputs"]) for r in data["digital_twin_runs"]], [("ciemat", {"days": 3})])

    def test_export_never_contains_full_card_number_or_cvv(self):
        from billing.models import PaymentMethod
        PaymentMethod.objects.create(user=self.user, card_number="4111111111111111", cvv="123", cardholder_name="Ann")
        raw = json.dumps(self._download())
        self.assertIn('"card_last4": "1111"', raw)
        self.assertNotIn("4111111111111111", raw)
        self.assertNotIn('"123"', raw)

    def test_export_includes_readable_html_copy(self):
        import io, zipfile
        from projects.models import Project
        Project.objects.create(name="<script>Mine</script>", creator=self.user)
        response = self.client.get(reverse("download_personal_data"))
        html = zipfile.ZipFile(io.BytesIO(response.content)).read("personal_data.html").decode()
        self.assertIn("Projects you created", html)
        self.assertIn("&lt;script&gt;Mine&lt;/script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_export_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("download_personal_data"))
        self.assertEqual(response.status_code, 302)


class AccountDeletionTests(TestCase):

    def setUp(self):
        import datetime
        from unittest.mock import patch
        from allauth.socialaccount.models import SocialAccount
        from django.utils import timezone
        from accounts.models import PrivacyRequest
        self.admin = User.objects.create_superuser(email="admin@example.com", password="testpass123")
        self.user = User.objects.create_user(email="leaving@example.com", password="testpass123", is_active=True)
        SocialAccount.objects.create(user=self.user, provider="keycloak", uid="kc-leaving")
        self.today = timezone.localdate()
        self.pr = PrivacyRequest.objects.create(
            user=self.user, email=self.user.email, kind="deletion", status="approved", scheduled_for=self.today,
        )
        self.tomorrow = self.today + datetime.timedelta(days=1)

        patcher = patch("accounts.services.privacy_requests.async_task")
        self.async_task = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("accounts.services.privacy_requests.KeycloakUserSyncClient")
        self.keycloak = patcher.start().return_value
        self.keycloak.delete_user.return_value = {"success": True}
        self.addCleanup(patcher.stop)

    def _delete(self):
        from accounts.services.privacy_requests import delete_account
        with self.captureOnCommitCallbacks(execute=True):
            delete_account(self.pr, self.admin)

    def test_deletes_django_and_keycloak_user_and_emails_them(self):
        self._delete()
        self.assertFalse(User.objects.filter(email="leaving@example.com").exists())
        self.keycloak.delete_user.assert_called_once_with("kc-leaving")
        self.pr.refresh_from_db()
        self.assertEqual((self.pr.status, self.pr.user, self.pr.email), ("completed", None, "leaving@example.com"))
        self.assertEqual(self.async_task.call_args[0][0], "accounts.tasks.send_account_deleted_email")

    def test_keycloak_failure_rolls_back_the_django_delete(self):
        from accounts.services.privacy_requests import AccountDeletionError
        self.keycloak.delete_user.return_value = {"error": "Failed."}
        with self.assertRaises(AccountDeletionError):
            self._delete()
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.pr.refresh_from_db()
        self.assertEqual(self.pr.status, "approved")
        self.async_task.assert_not_called()

    def test_keycloak_auth_failure_deletes_nothing(self):
        from accounts.services.privacy_requests import AccountDeletionError
        self.keycloak.token = None
        with self.assertRaises(AccountDeletionError):
            self._delete()
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.keycloak.delete_user.assert_not_called()

    def test_team_member_who_joined_first_becomes_admin(self):
        import datetime
        from django.utils import timezone
        from accounts.models import Notification, Profile, Team
        team = Team.objects.create(name="Grid")
        now = timezone.now()
        Profile.objects.filter(user=self.user).update(team=team, team_role="admin", team_joined_at=now - datetime.timedelta(days=30))
        first, later = (User.objects.create_user(email=f"{n}@example.com", password="testpass123") for n in ("first", "later"))
        Profile.objects.filter(user=later).update(team=team, team_role="member", team_joined_at=now - datetime.timedelta(days=1))
        Profile.objects.filter(user=first).update(team=team, team_role="member", team_joined_at=now - datetime.timedelta(days=10))
        self._delete()
        self.assertEqual(Profile.objects.get(user=first).team_role, "admin")
        self.assertEqual(Profile.objects.get(user=later).team_role, "member")
        self.assertTrue(Notification.objects.filter(recipient=first, message__contains="admin of the team Grid").exists())

    def test_team_left_with_no_members_is_deleted(self):
        from django.utils import timezone
        from accounts.models import Profile, Team, TeamInvite
        team = Team.objects.create(name="Solo")
        Profile.objects.filter(user=self.user).update(team=team, team_role="admin", team_joined_at=timezone.now())
        TeamInvite.objects.create(team=team, email="pending@example.com", invited_by=self.user, expires_at=timezone.now())
        self._delete()
        self.assertFalse(Team.objects.filter(pk=team.pk).exists())
        self.assertFalse(TeamInvite.objects.exists())

    def test_team_with_members_is_kept(self):
        from django.utils import timezone
        from accounts.models import Profile, Team
        team = Team.objects.create(name="Grid")
        Profile.objects.filter(user=self.user).update(team=team, team_role="admin", team_joined_at=timezone.now())
        member = User.objects.create_user(email="member@example.com", password="testpass123")
        Profile.objects.filter(user=member).update(team=team, team_role="member", team_joined_at=timezone.now())
        self._delete()
        self.assertTrue(Team.objects.filter(pk=team.pk).exists())

    def test_invites_received_are_deleted(self):
        from accounts.models import Team, TeamInvite
        from django.utils import timezone
        team = Team.objects.create(name="Grid")
        for email in ("LEAVING@example.com", "stays@example.com"):
            TeamInvite.objects.create(team=team, email=email, invited_by=self.admin, expires_at=timezone.now())
        self._delete()
        self.assertEqual(list(TeamInvite.objects.values_list("email", flat=True)), ["stays@example.com"])

    def test_admin_save_does_not_undo_a_cancel(self):
        from accounts.admin import PrivacyRequestAdmin
        from accounts.models import PrivacyRequest
        from django.contrib.admin.sites import site
        stale = PrivacyRequest.objects.get(pk=self.pr.pk)
        PrivacyRequest.objects.filter(pk=self.pr.pk).update(status="cancelled")
        stale.admin_note = "Noted"
        PrivacyRequestAdmin(PrivacyRequest, site).save_model(None, stale, None, True)
        self.pr.refresh_from_db()
        self.assertEqual((self.pr.status, self.pr.admin_note), ("cancelled", "Noted"))

    def test_user_with_open_request_cannot_be_deleted_from_users_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin:accounts_user_delete", args=[self.user.pk]), {"post": "yes"})
        self.assertEqual(response.status_code, 403)
        self.client.post(reverse("admin:accounts_user_changelist"), {
            "action": "delete_selected", "_selected_action": [self.user.pk], "post": "yes",
        })
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_privacy_requests_cannot_be_deleted_in_admin(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin:accounts_privacyrequest_delete", args=[self.pr.pk]), {"post": "yes"})
        self.assertEqual(response.status_code, 403)

    def test_not_before_the_scheduled_day(self):
        from accounts.services.privacy_requests import AccountDeletionError
        self.pr.scheduled_for = self.tomorrow
        self.pr.save()
        with self.assertRaises(AccountDeletionError):
            self._delete()
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.keycloak.delete_user.assert_not_called()

    def test_not_after_the_user_cancelled(self):
        from accounts.services.privacy_requests import AccountDeletionError, cancel_privacy_request
        self.assertTrue(cancel_privacy_request(self.user, self.pr.pk))
        with self.assertRaises(AccountDeletionError):
            self._delete()
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_admin_approve_button_saves_the_note_first(self):
        self.pr.status = "pending"
        self.pr.scheduled_for = None
        self.pr.save()
        self.client.force_login(self.admin)
        url = reverse("admin:accounts_privacyrequest_change", args=[self.pr.pk])
        response = self.client.post(url, {"admin_note": "See you", "_approve": "1"})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.pr.refresh_from_db()
        self.assertEqual((self.pr.status, self.pr.admin_note), ("approved", "See you"))

    def test_admin_delete_button(self):
        self.client.force_login(self.admin)
        url = reverse("admin:accounts_privacyrequest_change", args=[self.pr.pk])
        self.assertContains(self.client.get(url), 'name="_delete_account"')
        self.client.post(url, {"admin_note": "", "_delete_account": "1"})
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    @override_settings(ADMINS=[("Admin", "admins@example.com")])
    def test_reminder_lists_only_deletions_due_today(self):
        from django.core import mail
        from accounts.models import PrivacyRequest
        from accounts.tasks import remind_admins_of_due_deletions
        other = User.objects.create_user(email="later@example.com", password="testpass123")
        PrivacyRequest.objects.create(user=other, email=other.email, kind="deletion", status="approved", scheduled_for=self.tomorrow)
        remind_admins_of_due_deletions()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("leaving@example.com", mail.outbox[0].body)
        self.assertNotIn("later@example.com", mail.outbox[0].body)


class NotificationsTests(TestCase):

    def setUp(self):
        from accounts.models import Notification
        self.user = User.objects.create_user(email="notified@example.com", password="testpass123", is_active=True)
        self.other = User.objects.create_user(email="other@example.com", password="testpass123", is_active=True)
        self.read = Notification.objects.create(recipient=self.user, message="Old news", url="/datasets/", is_read=True)
        self.unread = Notification.objects.create(recipient=self.user, message="Fresh news", url="")
        Notification.objects.create(recipient=self.other, message="Not yours")
        self.client.force_login(self.user)

    def test_page_lists_read_and_unread_of_the_user_only(self):
        response = self.client.get(reverse("notifications"))
        self.assertContains(response, "Old news")
        self.assertContains(response, "Fresh news")
        self.assertNotContains(response, "Not yours")

    def test_unread_filter_hides_read_ones(self):
        response = self.client.get(reverse("notifications"), {"filter": "unread"})
        self.assertContains(response, "Fresh news")
        self.assertNotContains(response, "Old news")

    def test_mark_all_read_only_touches_the_user(self):
        from accounts.models import Notification
        response = self.client.post(reverse("mark_all_notifications_read"), {"next": "https://evil.example.com/"})
        self.assertRedirects(response, reverse("notifications"), fetch_redirect_response=False)
        self.assertFalse(Notification.objects.filter(recipient=self.user, is_read=False).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.other, is_read=False).exists())

    def test_read_without_url_goes_to_notifications_page(self):
        response = self.client.post(reverse("read_notification", args=[self.unread.id]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.json()["url"], reverse("notifications"))

    def test_bell_counts_only_real_unread_notifications(self):
        # The user has no team and an empty profile; those used to be added to the bell as reminders.
        response = self.client.get(reverse("notifications"))
        self.assertEqual(response.context["header_notifications_count"], 1)
        self.assertEqual([n["message"] for n in response.context["header_notifications"]], ["Fresh news"])

    def test_set_read_toggles_both_ways_and_stays_on_the_page(self):
        url = reverse("set_notification_read", args=[self.read.id])
        response = self.client.post(url, {"is_read": "0", "next": reverse("notifications") + "?filter=all"})
        self.assertRedirects(response, reverse("notifications") + "?filter=all", fetch_redirect_response=False)
        self.read.refresh_from_db()
        self.assertFalse(self.read.is_read)
        self.client.post(url, {"is_read": "1"})
        self.read.refresh_from_db()
        self.assertTrue(self.read.is_read)

    def test_set_read_on_someone_elses_notification_is_404(self):
        from accounts.models import Notification
        theirs = Notification.objects.get(recipient=self.other)
        response = self.client.post(reverse("set_notification_read", args=[theirs.id]), {"is_read": "1"})
        self.assertEqual(response.status_code, 404)

    def test_page_groups_notifications_by_day(self):
        from datetime import timedelta
        from django.utils import timezone
        from accounts.models import Notification
        Notification.objects.filter(pk=self.read.pk).update(created_at=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse("notifications"))
        self.assertEqual([d["label"] for d in response.context["notification_days"]], ["Today", "Yesterday"])

    def test_pagination_shows_numbered_pages_with_ellipsis(self):
        from accounts.models import Notification
        Notification.objects.bulk_create(Notification(recipient=self.user, message=f"n{i}") for i in range(200))
        response = self.client.get(reverse("notifications"), {"page": 6})
        self.assertEqual(list(response.context["page_range"]), [1, "…", 5, 6, 7, "…", 11])
        self.assertContains(response, 'href="?filter=all&page=11"')

    def test_set_read_rejects_a_missing_or_unknown_value(self):
        url = reverse("set_notification_read", args=[self.read.id])
        for data in ({}, {"is_read": "yes"}):
            self.assertEqual(self.client.post(url, data).status_code, 400)
        self.read.refresh_from_db()
        self.assertTrue(self.read.is_read)

    def test_header_exposes_limit_and_render_time_for_the_poll(self):
        from accounts.models import Notification
        response = self.client.get(reverse("notifications"))
        self.assertEqual(response.context["header_notifications_limit"], Notification.DROPDOWN_LIMIT)
        self.assertGreater(response.context["header_notifications_rendered_at_ms"], 0)

    def test_ago_filter_says_just_now_under_a_minute(self):
        from datetime import timedelta
        from django.utils import timezone
        from accounts.templatetags.notification_tags import ago
        self.assertEqual(ago(timezone.now() - timedelta(seconds=10)), "just now")
        self.assertEqual(ago(timezone.now() - timedelta(minutes=5)), "5 minutes ago")
