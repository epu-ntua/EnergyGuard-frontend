"""Who may create and version trustworthiness assessments.

Creating an assessment writes to the project, so it needs write access
(`Project.can_edit`): the creator or an edit collaborator. Read access to a
public project, or a view-only collaboration, is not enough. Viewing an existing
assessment still only needs read access.
"""

import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse

from projects.models import Project, ProjectCollaborator
from trustworthiness.models import Assessment


def make_user(email):
    # Creating a user registers it in MLflow (accounts.models signal); keep tests offline.
    with patch("projects.services.mlflow_client.create_mlflow_user"):
        return get_user_model().objects.create_user(email=email, password="pw-for-tests")


class PermissionFixture(TestCase):
    """A public project with its creator, an edit and a view collaborator, and a stranger."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner@example.com")
        cls.editor = make_user("editor@example.com")
        cls.viewer = make_user("viewer@example.com")
        cls.stranger = make_user("stranger@example.com")
        cls.project = Project.objects.create(name="Public project", creator=cls.owner, visibility=True)
        ProjectCollaborator.objects.create(
            collaborator=cls.editor, project=cls.project, permission_level=ProjectCollaborator.Permission.EDIT,
        )
        ProjectCollaborator.objects.create(
            collaborator=cls.viewer, project=cls.project, permission_level=ProjectCollaborator.Permission.VIEW,
        )

    def assessments(self, assessment_type):
        return Assessment.objects.filter(project=self.project, assessment_type=assessment_type)

    def can_write_cases(self):
        return [(self.owner, True), (self.editor, True), (self.viewer, False), (self.stranger, False)]


class RobustnessAssessmentPermissionTests(PermissionFixture):
    def submit(self, user, **extra):
        self.client.force_login(user)
        config = SimpleUploadedFile("config.yaml", b"model:\n  backend: mlflow\n", content_type="application/x-yaml")
        with patch("robustness.views.threading.Thread") as thread:
            response = self.client.post(
                reverse("robustness:config_input"),
                {"config_file": config, "project_id": self.project.pk, **extra},
            )
        # The evaluation thread never ran, so remove the temp file it would have deleted.
        for call in thread.call_args_list:
            temp_path = call.kwargs["args"][2]
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return response

    def test_only_users_who_can_edit_create_an_assessment(self):
        for user, allowed in self.can_write_cases():
            with self.subTest(user=user.email):
                before = self.assessments(Assessment.AssessmentType.ROBUSTNESS).count()
                response = self.submit(user)
                self.assertEqual(response.status_code, 302)
                after = self.assessments(Assessment.AssessmentType.ROBUSTNESS).count()
                self.assertEqual(after - before, 1 if allowed else 0)

    def test_versioning_needs_write_access_to_the_parent_project(self):
        parent = Assessment.objects.create(
            project=self.project, assessment_type=Assessment.AssessmentType.ROBUSTNESS, input_data={"config": {}},
        )
        own_project = Project.objects.create(name="Viewer's own", creator=self.viewer)
        self.client.force_login(self.viewer)
        config = SimpleUploadedFile("config.yaml", b"model:\n  backend: mlflow\n", content_type="application/x-yaml")
        with patch("robustness.views.threading.Thread") as thread:
            self.client.post(
                reverse("robustness:config_input"),
                {"config_file": config, "project_id": own_project.pk, "parent_assessment_id": parent.pk},
            )
        for call in thread.call_args_list:
            temp_path = call.kwargs["args"][2]
            if os.path.exists(temp_path):
                os.remove(temp_path)
        created = Assessment.objects.get(project=own_project)
        self.assertIsNone(created.parent_assessment)
        self.assertEqual(created.version, 1)

    def test_edit_needs_write_access_and_view_needs_read_access(self):
        assessment = Assessment.objects.create(
            project=self.project, assessment_type=Assessment.AssessmentType.ROBUSTNESS, input_data={"config": {}},
        )
        edit_url = reverse("robustness:edit_assessment", args=[assessment.pk])
        view_url = reverse("robustness:view_assessment", args=[assessment.pk])
        for user, allowed in self.can_write_cases():
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(edit_url).status_code, 200 if allowed else 404)
                # The project is public, so everyone may still look at it.
                self.assertEqual(self.client.get(view_url).status_code, 200)


class CodeAnalysisAssessmentPermissionTests(PermissionFixture):
    def submit(self, user, **extra):
        self.client.force_login(user)
        with patch("code_analysis.views.threading.Thread"):
            return self.client.post(
                reverse("code_analysis:processing"),
                {
                    "source_type": "GitHub Repository",
                    "repo_url": "https://github.com/example/repo",
                    "project_id": self.project.pk,
                    **extra,
                },
            )

    def test_only_users_who_can_edit_create_an_assessment(self):
        for user, allowed in self.can_write_cases():
            with self.subTest(user=user.email):
                before = self.assessments(Assessment.AssessmentType.CODE_ANALYSIS).count()
                response = self.submit(user)
                self.assertEqual(response.status_code, 302)
                after = self.assessments(Assessment.AssessmentType.CODE_ANALYSIS).count()
                self.assertEqual(after - before, 1 if allowed else 0)

    def test_versioning_needs_write_access_to_the_parent_project(self):
        parent = Assessment.objects.create(
            project=self.project, assessment_type=Assessment.AssessmentType.CODE_ANALYSIS,
            input_data={"source": "GitHub Repository", "repo_url": "https://github.com/example/repo"},
        )
        own_project = Project.objects.create(name="Viewer's own", creator=self.viewer)
        self.client.force_login(self.viewer)
        with patch("code_analysis.views.threading.Thread"):
            self.client.post(
                reverse("code_analysis:processing"),
                {
                    "source_type": "GitHub Repository",
                    "repo_url": "https://github.com/example/repo",
                    "project_id": own_project.pk,
                    "parent_assessment_id": parent.pk,
                },
            )
        created = Assessment.objects.get(project=own_project)
        self.assertIsNone(created.parent_assessment)
        self.assertEqual(created.version, 1)

    def test_edit_needs_write_access_and_view_needs_read_access(self):
        assessment = Assessment.objects.create(
            project=self.project, assessment_type=Assessment.AssessmentType.CODE_ANALYSIS,
            input_data={"source": "GitHub Repository", "repo_url": "https://github.com/example/repo"},
        )
        edit_url = reverse("code_analysis:edit_assessment", args=[assessment.pk])
        view_url = reverse("code_analysis:view_assessment", args=[assessment.pk])
        for user, allowed in self.can_write_cases():
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(edit_url).status_code, 200 if allowed else 404)
                self.assertEqual(self.client.get(view_url).status_code, 200)


class AiActAssessmentPermissionTests(PermissionFixture):
    def sync_completed_questionnaire(self, user):
        from questionnaire import engine, views

        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = user
        request.session["ai_act_project_id"] = str(self.project.pk)

        state = {"tracks": {name: views._empty_track_state() for name in engine.TRACK_NAMES}, "active_track": "ai_system"}
        state["tracks"]["ai_system"].update(started=True, completed=True, role="provider", risk_category="minimal_risk")
        views._sync_trustworthiness(request, state)

    def test_only_users_who_can_edit_create_an_assessment(self):
        for user, allowed in self.can_write_cases():
            with self.subTest(user=user.email):
                before = self.assessments(Assessment.AssessmentType.AI_ACT).count()
                self.sync_completed_questionnaire(user)
                after = self.assessments(Assessment.AssessmentType.AI_ACT).count()
                self.assertEqual(after - before, 1 if allowed else 0)


class HubProjectPickerTests(PermissionFixture):
    def test_picker_offers_only_projects_the_user_can_edit(self):
        Assessment.objects.create(
            project=self.project, assessment_type=Assessment.AssessmentType.CODE_ANALYSIS,
            status=Assessment.Status.COMPLETED,
        )
        url = reverse("trustworthiness:trustworthiness")
        for user, offered in [(self.owner, True), (self.editor, True), (self.viewer, False)]:
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(url)
                picker_ids = {p["id"] for p in response.context["projects_data"]}
                self.assertEqual(self.project.pk in picker_ids, offered)
                # Results of projects the user can read stay listed, editable or not.
                result_projects = {a["project"] for a in response.context["assessment_runs_data"]}
                self.assertIn(self.project.name, result_projects)
