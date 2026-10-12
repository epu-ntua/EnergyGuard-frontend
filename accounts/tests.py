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

    def test_resolve_notifies_user_once(self):
        from accounts.models import Notification, PrivacyRequest
        from accounts.services.privacy_requests import resolve_privacy_request
        pr = PrivacyRequest.objects.create(user=self.user, email=self.user.email, kind="deletion")
        self.assertTrue(resolve_privacy_request(pr, PrivacyRequest.Status.COMPLETED, self.other))
        self.assertFalse(resolve_privacy_request(pr, PrivacyRequest.Status.REJECTED, self.other))
        pr.refresh_from_db()
        self.assertEqual(pr.status, "completed")
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)

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
