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
