import json
from collections import Counter
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.views.ai_models import AI_MODELS, CATEGORY_LABELS


class AIModelsViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="testpass123", is_active=True
        )

    def test_requires_login(self):
        response = self.client.get(reverse("ai_models"))
        self.assertEqual(response.status_code, 302)

    def test_renders_for_logged_in_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("ai_models"))
        self.assertEqual(response.status_code, 200)
        for model in AI_MODELS:
            self.assertContains(response, model["name"])

    def test_broken_cta_url_name_does_not_crash_page(self):
        """A single AI model referencing a renamed/removed URL name must not 500 the whole page."""
        self.client.force_login(self.user)
        broken_models = [dict(m) for m in AI_MODELS]
        broken_models[0]["cta_url_name"] = "this-url-name-does-not-exist"
        with patch("core.views.ai_models.AI_MODELS", broken_models):
            response = self.client.get(reverse("ai_models"))
        self.assertEqual(response.status_code, 200)


class DashboardAIModelsChartTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="testpass123", is_active=True
        )
        self.client.force_login(self.user)

    def test_donut_data_matches_all_ai_models_including_coming_soon(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        marker = 'id="ai-models-donut-data"'
        start = content.index(marker)
        script_start = content.index(">", start) + 1
        script_end = content.index("</script>", script_start)
        chart_data = json.loads(content[script_start:script_end])

        expected_counts = Counter(model["category"] for model in AI_MODELS)
        actual_counts = {row["category"]: row["value"] for row in chart_data}

        # Every model must be counted, including "coming soon" ones (no cta_url/request_access).
        self.assertEqual(sum(actual_counts.values()), len(AI_MODELS))
        for category_key, expected_count in expected_counts.items():
            self.assertEqual(actual_counts[CATEGORY_LABELS[category_key]], expected_count)


@override_settings(ADMINS=[("Admin", "admin@example.com")])
class RequestAIModelAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="testpass123", is_active=True
        )
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse("ai_model_request_access"), {"model_slug": "deeptsf"}
        )
        self.assertEqual(response.status_code, 302)

    def test_get_not_allowed(self):
        response = self.client.get(reverse("ai_model_request_access"))
        self.assertEqual(response.status_code, 405)

    def test_unknown_slug_shows_error_and_sends_no_mail(self):
        response = self.client.post(
            reverse("ai_model_request_access"), {"model_slug": "does-not-exist"}
        )
        self.assertRedirects(response, reverse("ai_models"))
        self.assertEqual(len(mail.outbox), 0)

    def test_valid_slug_emails_admins(self):
        response = self.client.post(
            reverse("ai_model_request_access"), {"model_slug": "deeptsf"}
        )
        self.assertRedirects(response, reverse("ai_models"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("DeepTSF", mail.outbox[0].subject)
        self.assertIn(self.user.email, mail.outbox[0].body)
