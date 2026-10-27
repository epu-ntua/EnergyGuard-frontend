import json
from collections import Counter
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from core.views.ai_models import AI_MODELS, CATEGORY_LABELS
from core.views.journeys import JOURNEYS


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

    def test_donut_data_counts_only_available_ai_models(self):
        """Since ef3fc44 the dashboard counts what users can actually use: models
        that are "request access" or "coming soon" are left out of the donut."""
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        marker = 'id="ai-models-donut-data"'
        start = content.index(marker)
        script_start = content.index(">", start) + 1
        script_end = content.index("</script>", script_start)
        chart_data = json.loads(content[script_start:script_end])

        available = [model for model in AI_MODELS if model["badge"] == "available"]
        expected_counts = {
            CATEGORY_LABELS[category_key]: count
            for category_key, count in Counter(model["category"] for model in available).items()
        }
        actual_counts = {row["category"]: row["value"] for row in chart_data}

        self.assertEqual(actual_counts, expected_counts)
        self.assertEqual(sum(actual_counts.values()), len(available))


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

    def test_existing_slug_without_request_access_shows_error_and_sends_no_mail(self):
        response = self.client.post(
            reverse("ai_model_request_access"), {"model_slug": "smart-energy-optimiser"}
        )
        self.assertRedirects(response, reverse("ai_models"))
        self.assertEqual(len(mail.outbox), 0)

    def test_ajax_existing_slug_without_request_access_returns_json_error(self):
        response = self.client.post(
            reverse("ai_model_request_access"),
            {"model_slug": "smart-energy-optimiser"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data["success"])
        self.assertEqual(len(mail.outbox), 0)

    def test_valid_slug_emails_admins(self):
        response = self.client.post(
            reverse("ai_model_request_access"), {"model_slug": "deeptsf"}
        )
        self.assertRedirects(response, reverse("ai_models"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("DeepTSF", mail.outbox[0].subject)
        self.assertIn(self.user.email, mail.outbox[0].body)

    def test_ajax_valid_slug_returns_json_success_and_emails_admins(self):
        response = self.client.post(
            reverse("ai_model_request_access"),
            {"model_slug": "deeptsf"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertIn("DeepTSF", data["message"])
        self.assertEqual(len(mail.outbox), 1)

    def test_ajax_unknown_slug_returns_json_error_and_sends_no_mail(self):
        response = self.client.post(
            reverse("ai_model_request_access"),
            {"model_slug": "does-not-exist"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data["success"])
        self.assertEqual(len(mail.outbox), 0)

    def test_ajax_mail_failure_returns_json_error(self):
        with patch("core.views.ai_models.mail_admins", side_effect=Exception("smtp down")):
            response = self.client.post(
                reverse("ai_model_request_access"),
                {"model_slug": "deeptsf"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 502)
        data = json.loads(response.content)
        self.assertFalse(data["success"])


class LegalDocRedirectTests(TestCase):
    def test_extensionless_links_inside_the_pdfs_redirect_to_the_published_files(self):
        from main.urls import LEGAL_DOC_ALIASES
        for alias, filename in LEGAL_DOC_ALIASES.items():
            response = self.client.get(f'/static/assets/docs/{alias}')
            self.assertRedirects(response, f'/static/assets/docs/{filename}', fetch_redirect_response=False)


class JourneysViewTests(TestCase):
    def setUp(self):
        # Creating a user registers it in MLflow (accounts.models signal); keep the test offline.
        with patch("projects.services.mlflow_client.create_mlflow_user"):
            self.user = User.objects.create_user(
                email="journeys@example.com", password="testpass123", is_active=True
            )

    def test_requires_login(self):
        self.assertEqual(self.client.get(reverse("journeys")).status_code, 302)
        self.assertEqual(self.client.get(reverse("journey_detail", args=["first-experiment"])).status_code, 302)
        self.assertEqual(self.client.get(reverse("documentation")).status_code, 302)

    def test_list_shows_every_journey(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("journeys"))
        self.assertEqual(response.status_code, 200)
        for journey in JOURNEYS:
            self.assertContains(response, journey["title"])
            self.assertContains(response, reverse("journey_detail", args=[journey["slug"]]))

    def test_detail_shows_every_step_and_its_link(self):
        self.client.force_login(self.user)
        for journey in JOURNEYS:
            response = self.client.get(reverse("journey_detail", args=[journey["slug"]]))
            self.assertEqual(response.status_code, 200)
            for step in journey["steps"]:
                self.assertContains(response, step["title"])
                if step.get("link"):
                    self.assertContains(response, reverse(step["link"]["url_name"], kwargs=step["link"].get("kwargs")))

    def test_unknown_journey_is_not_found(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("journey_detail", args=["no-such-journey"])).status_code, 404)

    def test_broken_step_link_does_not_crash_the_page(self):
        self.client.force_login(self.user)
        broken = [dict(JOURNEYS[0], steps=[dict(JOURNEYS[0]["steps"][0], link={"label": "x", "url_name": "no-such-url"})])]
        with patch("core.views.journeys.JOURNEYS_BY_SLUG", {broken[0]["slug"]: broken[0]}):
            response = self.client.get(reverse("journey_detail", args=[broken[0]["slug"]]))
        self.assertEqual(response.status_code, 200)

    def test_sidebar_links_to_documentation_not_to_journeys(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        html = response.content.decode()
        sidebar = html[html.index('id="navbarVerticalNav"'):html.index('navbar-vertical-footer')]
        self.assertIn(f'href="{reverse("documentation")}"', sidebar)
        self.assertNotIn(f'href="{reverse("journeys")}"', sidebar)

    def test_team_banner_suggests_the_journeys(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, 'id="dashboard-team-banner"')
        self.assertContains(response, 'data-dismiss-storage="session"')
        self.assertContains(response, f'href="{reverse("journeys")}"')
        self.assertContains(response, f'href="{reverse("team_management")}?create=1"')

    def test_team_members_get_the_journeys_banner_instead(self):
        from accounts.models import Profile, Team
        self.user.profile.team = Team.objects.create(name="Grid team")
        self.user.profile.team_role = Profile.Team_Role.ADMIN
        self.user.profile.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, 'id="dashboard-team-banner"')
        self.assertContains(response, 'id="dashboard-journeys-banner"')
        self.assertContains(response, f'href="{reverse("journeys")}"')

    def test_documentation_getting_started_leads_to_the_journeys(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("documentation"))
        self.assertContains(response, "Getting Started")
        self.assertContains(response, f'href="{reverse("journeys")}"')
        html = response.content.decode()
        content = html[html.index("Documentation</h2>"):html.index("<footer")]
        self.assertNotIn('href="#"', content)  # no dead cards left

    def test_journeys_live_under_documentation(self):
        self.assertEqual(reverse("journeys"), "/documentation/getting-started/")
        self.client.force_login(self.user)
        response = self.client.get(reverse("journey_detail", args=[JOURNEYS[0]["slug"]]))
        self.assertContains(response, f'<a href="{reverse("documentation")}">Documentation</a>')
        self.assertContains(response, f'<a href="{reverse("journeys")}">Getting Started</a>')


class JourneyInlineLinkTests(TestCase):
    def test_links_to_another_journey_and_escapes_the_rest(self):
        from core.views.journeys import _render_paragraph

        html = _render_paragraph('Use <b>this</b> or [contribute your own](journey:contribute-dataset).')
        self.assertIn(f'<a href="{reverse("journey_detail", args=["contribute-dataset"])}">contribute your own</a>', html)
        self.assertIn('&lt;b&gt;this&lt;/b&gt;', html)

    def test_links_to_a_platform_page(self):
        from core.views.journeys import _render_paragraph

        self.assertIn(f'<a href="{reverse("datasets_list")}">datasets</a>', _render_paragraph('See [datasets](datasets_list).'))

    def test_unknown_target_is_shown_as_plain_text(self):
        from core.views.journeys import _render_paragraph

        self.assertEqual(_render_paragraph('A [missing](journey:no-such-journey) link.'), 'A missing link.')


class NextJourneyTests(TestCase):
    def setUp(self):
        with patch("projects.services.mlflow_client.create_mlflow_user"):
            self.user = User.objects.create_user(email="next@example.com", password="testpass123", is_active=True)

    def test_each_journey_suggests_the_one_after_it(self):
        self.client.force_login(self.user)
        for journey, following in zip(JOURNEYS, JOURNEYS[1:]):
            with self.subTest(journey["slug"]):
                response = self.client.get(reverse("journey_detail", args=[journey["slug"]]))
                self.assertContains(response, "Next journey")
                self.assertContains(response, reverse("journey_detail", args=[following["slug"]]))
                self.assertContains(response, following["title"])

    def test_last_journey_has_no_next_journey(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("journey_detail", args=[JOURNEYS[-1]["slug"]]))
        self.assertNotContains(response, "Next journey")

    def test_cards_follow_the_order_of_journeys(self):
        self.client.force_login(self.user)
        html = self.client.get(reverse("journeys")).content.decode()
        positions = [html.index(reverse("journey_detail", args=[j["slug"]])) for j in JOURNEYS]
        self.assertEqual(positions, sorted(positions))
