"""Who may create and version trustworthiness assessments.

Creating an assessment writes to the project, so it needs write access
(`Project.can_edit`): the creator or an edit collaborator. Read access to a
public project, or a view-only collaboration, is not enough. Viewing an existing
assessment still only needs read access.
"""

import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
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


class AiActRestartTests(PermissionFixture):
    """A restart, from the intro or the results page, records a new Assessment on the same project."""

    def finish_questionnaire(self):
        # Jump to the last step (AI-8, AI literacy) and answer it, so the
        # track completes through the real submit view.
        from questionnaire import engine, views

        session = self.client.session
        state = {
            "tracks": {name: views._empty_track_state() for name in engine.TRACK_NAMES},
            "active_track": "ai_system",
            "project_id": session.get("ai_act_project_id"),
        }
        state["tracks"]["ai_system"].update(
            started=True, current_step="AI-8", role="provider", risk_category="minimal_risk",
        )
        session[views.SESSION_KEY] = state
        session.save()
        url = reverse("questionnaire:submit_branching", kwargs={"track": "ai_system", "step_id": "AI-8"})
        self.client.post(url, {"answer": "YES"})

    def test_restart_keeps_the_project_and_records_a_new_assessment(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})
        self.finish_questionnaire()
        self.client.get(reverse("questionnaire:restart"))
        self.finish_questionnaire()

        self.assertEqual(self.assessments(Assessment.AssessmentType.AI_ACT).count(), 2)

    def assertFreshAttempt(self, project):
        from questionnaire import views

        state = self.client.session[views.SESSION_KEY]
        self.assertEqual(state["project_id"], str(project.pk))
        self.assertFalse(any(track["started"] for track in state["tracks"].values()))

    def test_picking_another_project_starts_a_new_attempt(self):
        from questionnaire import views

        other = Project.objects.create(name="Other project", creator=self.owner)
        self.client.force_login(self.owner)
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})
        self.finish_questionnaire()
        self.client.get(reverse("questionnaire:intro"), {"project_id": other.pk})

        self.assertFreshAttempt(other)
        self.assertNotIn("ai_act_assessment_id", self.client.session)
        # A new attempt that completes is recorded on the new project only.
        self.finish_questionnaire()
        self.assertEqual(Assessment.objects.filter(project=self.project).count(), 1)
        self.assertEqual(Assessment.objects.filter(project=other).count(), 1)

    def test_answers_saved_without_a_project_are_not_carried_into_one(self):
        from questionnaire import engine, views

        self.client.force_login(self.owner)
        session = self.client.session
        session[views.SESSION_KEY] = {
            "tracks": {name: views._empty_track_state() for name in engine.TRACK_NAMES}, "active_track": None,
        }
        session.save()
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})

        self.assertFreshAttempt(self.project)

    def test_the_same_project_resumes_its_attempt(self):
        from questionnaire import views

        self.client.force_login(self.owner)
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})
        self.finish_questionnaire()
        assessment_id = self.client.session["ai_act_assessment_id"]
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})

        self.assertIn(views.SESSION_KEY, self.client.session)
        self.assertEqual(self.client.session["ai_act_assessment_id"], assessment_id)
        # Completing it again updates its Assessment instead of adding one.
        self.finish_questionnaire()
        self.assertEqual(self.assessments(Assessment.AssessmentType.AI_ACT).count(), 1)

    def test_a_rejected_pick_leaves_the_current_attempt_alone(self):
        from questionnaire import views

        self.client.force_login(self.owner)
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})
        self.finish_questionnaire()
        before = {key: self.client.session[key] for key in (views.SESSION_KEY, "ai_act_project_id", "ai_act_assessment_id")}

        response = self.client.get(reverse("questionnaire:intro"), {"project_id": 999999})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            {key: self.client.session[key] for key in before}, before,
        )

    def test_an_assessment_deleted_since_is_recorded_anew(self):
        self.client.force_login(self.owner)
        self.client.get(reverse("questionnaire:intro"), {"project_id": self.project.pk})
        self.finish_questionnaire()
        Assessment.objects.filter(pk=self.client.session["ai_act_assessment_id"]).delete()

        with self.assertLogs("questionnaire.views", level="WARNING"):
            self.finish_questionnaire()

        recorded = self.assessments(Assessment.AssessmentType.AI_ACT).get()
        self.assertEqual(self.client.session["ai_act_assessment_id"], recorded.pk)

    def test_completing_without_a_project_records_nothing_and_warns(self):
        self.client.force_login(self.owner)
        with self.assertLogs("questionnaire.views", level="WARNING") as logs:
            self.finish_questionnaire()

        self.assertFalse(Assessment.objects.exists())
        self.assertIn("without a project", logs.output[0])

    def test_a_deleted_project_is_dropped_from_the_session(self):
        self.client.force_login(self.owner)
        doomed = Project.objects.create(name="Doomed", creator=self.owner)
        self.client.get(reverse("questionnaire:intro"), {"project_id": doomed.pk})
        doomed.delete()

        with self.assertLogs("trustworthiness.project_access", level="WARNING") as logs:
            self.finish_questionnaire()

        self.assertFalse(Assessment.objects.exists())
        self.assertIn("unknown project_id", logs.output[0])
        self.assertNotIn("ai_act_project_id", self.client.session)


class NoRunWithoutProjectTests(PermissionFixture):
    """Every assessment entry without a project the user can edit goes back to
    the hub's project picker, and no job starts."""

    def picker_url(self, assessment_type):
        return f"{reverse('trustworthiness:trustworthiness')}?{urlencode({'open_modal': assessment_type.label})}"

    def test_entry_pages_send_users_without_an_editable_project_to_the_picker(self):
        entries = [
            (reverse("questionnaire:intro"), Assessment.AssessmentType.AI_ACT),
            (reverse("trustworthiness:assessment_detail", args=["code-analysis"]), Assessment.AssessmentType.CODE_ANALYSIS),
            (reverse("code_analysis:select_source"), Assessment.AssessmentType.CODE_ANALYSIS),
            (reverse("code_analysis:configure_github"), Assessment.AssessmentType.CODE_ANALYSIS),
            (reverse("code_analysis:configure_upload"), Assessment.AssessmentType.CODE_ANALYSIS),
            (reverse("robustness:config_input"), Assessment.AssessmentType.ROBUSTNESS),
        ]
        for user, project_id, label in [
            (self.owner, None, "no project"),
            (self.owner, 999999, "unknown project"),
            (self.viewer, self.project.pk, "read-only project"),
        ]:
            self.client.force_login(user)
            query = {"project_id": project_id} if project_id else {}
            for url, assessment_type in entries:
                with self.subTest(case=label, url=url):
                    response = self.client.get(url, query)
                    self.assertRedirects(response, self.picker_url(assessment_type), fetch_redirect_response=False)

    def test_entry_pages_open_for_an_editable_project(self):
        self.client.force_login(self.editor)
        for url in [
            reverse("questionnaire:intro"),
            reverse("code_analysis:select_source"),
            reverse("robustness:config_input"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, {"project_id": self.project.pk}).status_code, 200)

    def test_ai_act_track_needs_a_project_in_the_session(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("questionnaire:start_track", args=["ai_system"]))
        self.assertRedirects(response, self.picker_url(Assessment.AssessmentType.AI_ACT), fetch_redirect_response=False)

    def test_the_picker_says_why_the_user_landed_there(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("robustness:config_input"), follow=True)
        self.assertEqual(
            [str(m) for m in get_messages(response.wsgi_request)],
            ["Choose a project you can edit to start the Adversarial Robustness."],
        )

    def submit_robustness(self, user, **data):
        self.client.force_login(user)
        config = SimpleUploadedFile("config.yaml", b"model:\n  backend: mlflow\n", content_type="application/x-yaml")
        temp_files = []
        real_tempfile = tempfile.NamedTemporaryFile

        def tracked_tempfile(*args, **kwargs):
            tmp = real_tempfile(*args, **kwargs)
            temp_files.append(tmp.name)
            return tmp

        with patch("robustness.views.threading.Thread") as thread, \
                patch("robustness.views.tempfile.NamedTemporaryFile", side_effect=tracked_tempfile):
            response = self.client.post(reverse("robustness:config_input"), {"config_file": config, **data})
        return response, thread, temp_files

    def submit_code_analysis(self, user, **data):
        self.client.force_login(user)
        with patch("code_analysis.views.threading.Thread") as thread:
            response = self.client.post(reverse("code_analysis:processing"), {
                "source_type": "GitHub Repository", "repo_url": "https://github.com/example/repo", **data,
            })
        return response, thread

    def test_submit_without_an_editable_project_starts_no_job(self):
        for user, data, label in [
            (self.owner, {}, "no project"),
            (self.viewer, {"project_id": self.project.pk}, "read-only project"),
        ]:
            with self.subTest(case=label, app="robustness"):
                response, thread, temp_files = self.submit_robustness(user, **data)
                self.assertRedirects(response, self.picker_url(Assessment.AssessmentType.ROBUSTNESS), fetch_redirect_response=False)
                thread.assert_not_called()
                self.assertEqual(temp_files, [])
            with self.subTest(case=label, app="code_analysis"):
                response, thread = self.submit_code_analysis(user, **data)
                self.assertRedirects(response, self.picker_url(Assessment.AssessmentType.CODE_ANALYSIS), fetch_redirect_response=False)
                thread.assert_not_called()
        self.assertFalse(Assessment.objects.exists())

    def test_submit_whose_assessment_cannot_be_saved_shows_an_error_and_starts_no_job(self):
        with patch.object(Assessment.objects, "create", side_effect=RuntimeError("db down")):
            with self.assertLogs("robustness.views", level="ERROR"):
                response, thread, temp_files = self.submit_robustness(self.owner, project_id=self.project.pk)
            with self.assertLogs("code_analysis.views", level="ERROR"):
                ca_response, ca_thread = self.submit_code_analysis(self.owner, project_id=self.project.pk)

        self.assertContains(response, "The assessment could not be started.")
        thread.assert_not_called()
        self.assertEqual(len(temp_files), 1)
        self.assertFalse(os.path.exists(temp_files[0]))

        self.assertContains(ca_response, "The analysis could not be started.", status_code=500)
        ca_thread.assert_not_called()

    def test_new_analysis_links_keep_the_project(self):
        self.client.force_login(self.owner)
        for assessment_type, results_url, form_url in [
            (Assessment.AssessmentType.ROBUSTNESS, "robustness:view_assessment_results", "robustness:config_input"),
            (Assessment.AssessmentType.CODE_ANALYSIS, "code_analysis:view_assessment_results", "code_analysis:select_source"),
        ]:
            with self.subTest(assessment_type=assessment_type):
                assessment = Assessment.objects.create(
                    project=self.project, assessment_type=assessment_type,
                    status=Assessment.Status.COMPLETED, results={"report_meta": {}},
                )
                response = self.client.get(reverse(results_url, args=[assessment.pk]))
                self.assertContains(response, f'{reverse(form_url)}?project_id={self.project.pk}')


class JobPageAccessTests(PermissionFixture):
    """A job's pages need read access to the project of the Assessment that
    records the job; anyone else gets the same answer as for a missing job."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.private_project = Project.objects.create(name="Private project", creator=cls.owner, visibility=False)

    def setUp(self):
        from code_analysis import views as code_analysis_views
        from robustness import views as robustness_views

        self.robustness = robustness_views
        self.code_analysis = code_analysis_views
        self.addCleanup(robustness_views.EVAL_JOBS.clear)
        self.addCleanup(code_analysis_views.SCAN_JOBS.clear)

    def assessment_id(self, assessment_type, project):
        return Assessment.objects.create(project=project, assessment_type=assessment_type).pk

    def in_memory_jobs(self, job_id, project):
        """The same job_id, completed, in both apps' in-memory job stores."""
        for set_job, assessment_type in (
            (self.robustness._set_job, Assessment.AssessmentType.ROBUSTNESS),
            (self.code_analysis._set_scan_job, Assessment.AssessmentType.CODE_ANALYSIS),
        ):
            assessment_id = self.assessment_id(assessment_type, project) if project else None
            set_job(job_id, status="completed", result={}, assessment_id=assessment_id)

    def job_pages(self, job_id):
        """(url, visible(response)) for each job page: what a visible job
        answers, as opposed to a missing one."""
        not_404 = lambda r: r.status_code != 404
        return [
            # A completed job's results page hands over to its Assessment's.
            (reverse("robustness:results", args=[job_id]), not_404),
            (reverse("robustness:results_json", args=[job_id]), not_404),
            (reverse("code_analysis:results", args=[job_id]), lambda r: r.status_code == 302),
            (f"{reverse('robustness:processing')}?job={job_id}", not_404),
            (f"{reverse('robustness:job_status')}?job={job_id}", not_404),
            (f"{reverse('code_analysis:processing')}?job={job_id}", not_404),
            (f"{reverse('code_analysis:job_status_api')}?job={job_id}", not_404),
        ]

    def check(self, pages, cases):
        for user, visible in cases:
            self.client.force_login(user)
            for url, is_visible in pages:
                with self.subTest(user=user.email, url=url):
                    self.assertEqual(is_visible(self.client.get(url)), visible)

    def test_private_project_jobs_are_only_visible_to_its_members(self):
        self.in_memory_jobs("private-job", self.private_project)
        self.check(self.job_pages("private-job"), [(self.owner, True), (self.stranger, False)])

    def test_public_project_jobs_are_visible_like_its_assessments(self):
        self.in_memory_jobs("public-job", self.project)
        self.check(self.job_pages("public-job"), [(self.viewer, True), (self.stranger, True)])

    def test_a_job_no_assessment_records_is_visible_to_no_one(self):
        self.in_memory_jobs("orphan-job", None)
        self.check(self.job_pages("orphan-job"), [(self.owner, False)])

    def test_a_missing_job_answers_the_same_as_a_hidden_one(self):
        self.check(self.job_pages("no-such-job"), [(self.owner, False)])


class AssessmentResultsSourceTests(PermissionFixture):
    """Results are read from the Assessment only: a finished job hands over
    to its Assessment's results page, and the downloads go through it too."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.private_project = Project.objects.create(name="Private project", creator=cls.owner, visibility=False)

    def setUp(self):
        from code_analysis import views as code_analysis_views
        from robustness import views as robustness_views

        self.robustness = robustness_views
        self.code_analysis = code_analysis_views
        self.addCleanup(robustness_views.EVAL_JOBS.clear)
        self.addCleanup(code_analysis_views.SCAN_JOBS.clear)

    def completed(self, assessment_type, **input_data):
        return Assessment.objects.create(
            project=self.private_project, assessment_type=assessment_type,
            status=Assessment.Status.COMPLETED, results={"report_meta": {}}, input_data=input_data,
        )

    def test_submitting_records_the_job_id_on_the_assessment(self):
        self.client.force_login(self.owner)
        config = SimpleUploadedFile("config.yaml", b"model:\n  backend: mlflow\n", content_type="application/x-yaml")
        with patch("robustness.views.threading.Thread"), patch("code_analysis.views.threading.Thread"):
            robustness = self.client.post(reverse("robustness:config_input"), {"config_file": config, "project_id": self.project.pk})
            code_analysis = self.client.post(reverse("code_analysis:processing"), {
                "source_type": "GitHub Repository", "repo_url": "https://github.com/example/repo", "project_id": self.project.pk,
            })
        for response, assessment_type in (
            (robustness, Assessment.AssessmentType.ROBUSTNESS),
            (code_analysis, Assessment.AssessmentType.CODE_ANALYSIS),
        ):
            with self.subTest(assessment_type=assessment_type):
                job_id = self.assessments(assessment_type).get().input_data["job_id"]
                self.assertIn(f"job={job_id}", response.url)

    def test_a_finished_job_hands_over_to_its_assessments_results_page(self):
        self.client.force_login(self.owner)
        for set_job, assessment_type, app in (
            (self.robustness._set_job, Assessment.AssessmentType.ROBUSTNESS, "robustness"),
            (self.code_analysis._set_scan_job, Assessment.AssessmentType.CODE_ANALYSIS, "code_analysis"),
        ):
            with self.subTest(app=app):
                assessment = self.completed(assessment_type)
                set_job("job-1", status="completed", result={}, assessment_id=assessment.pk)
                response = self.client.get(reverse(f"{app}:results", args=["job-1"]))
                self.assertRedirects(
                    response, reverse(f"{app}:view_assessment_results", args=[assessment.pk]), fetch_redirect_response=False,
                )

    def test_the_robustness_job_records_its_results_and_backend_id_and_writes_no_file(self):
        assessment = Assessment.objects.create(project=self.project, assessment_type=Assessment.AssessmentType.ROBUSTNESS)
        with tempfile.NamedTemporaryFile(delete=False) as config:
            pass
        with patch("robustness.views._call_backend_api", return_value=({"report_meta": {}}, "backend-7")), \
                patch("pathlib.Path.write_text") as write_text:
            self.robustness._run_eval_job("job-1", "config", config.name, assessment_id=assessment.pk)
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, Assessment.Status.COMPLETED)
        self.assertEqual(assessment.results, {"report_meta": {}})
        self.assertEqual(assessment.input_data["backend_job_id"], "backend-7")
        write_text.assert_not_called()

    def test_downloads_need_read_access_to_the_assessment(self):
        code_analysis = self.completed(Assessment.AssessmentType.CODE_ANALYSIS)
        robustness = self.completed(Assessment.AssessmentType.ROBUSTNESS, backend_job_id="backend-7")
        backend = {"adversarial_examples": [{"attack_key": "fgsm"}]}
        pages = [
            reverse("code_analysis:assessment_results_json", args=[code_analysis.pk]),
            reverse("robustness:list_adversarial_csvs", args=[robustness.pk]),
        ]
        for user, status in ((self.owner, 200), (self.stranger, 404)):
            self.client.force_login(user)
            for url in pages:
                with self.subTest(user=user.email, url=url), \
                        self.settings(ROBUSTNESS_API_URL="http://backend"), \
                        patch("robustness.views.requests.get") as get:
                    get.return_value.json.return_value = backend
                    self.assertEqual(self.client.get(url).status_code, status)

        self.client.force_login(self.owner)
        with self.settings(ROBUSTNESS_API_URL="http://backend"), patch("robustness.views.requests.get") as get:
            get.return_value.json.return_value = backend
            items = self.client.get(pages[1]).json()["items"]
        get.assert_called_once_with("http://backend/api/evaluations/backend-7/adversarial-examples", timeout=10)
        self.assertEqual([item["attack_key"] for item in items], ["fgsm"])


class PurgeAssessmentReportFoldersTests(PermissionFixture):
    def setUp(self):
        base_dir = tempfile.TemporaryDirectory()
        self.addCleanup(base_dir.cleanup)
        self.base_dir = Path(base_dir.name)
        override = self.settings(BASE_DIR=self.base_dir)
        override.enable()
        self.addCleanup(override.disable)

    def folder(self, dir_name, name, meta, report):
        folder = self.base_dir / dir_name / name
        folder.mkdir(parents=True)
        (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (folder / "final_report.json").write_text(report, encoding="utf-8")
        return folder

    def run_command(self, *args):
        from django.core.management import call_command

        out = StringIO()
        call_command("purge_assessment_report_folders", *args, stdout=out)
        return out.getvalue()

    def test_deletes_only_what_the_database_holds_and_copies_what_it_lacks(self):
        robustness = Assessment.AssessmentType.ROBUSTNESS
        in_db = Assessment.objects.create(project=self.project, assessment_type=robustness, results={"a": 1})
        lacking = Assessment.objects.create(project=self.project, assessment_type=robustness, input_data={"job_id": "j2"})
        unreadable = Assessment.objects.create(project=self.project, assessment_type=robustness)
        folders = {
            "in_db": self.folder("robustness_reports", "b1", {"job_id": "j1", "backend_job_id": "b1", "assessment_id": in_db.pk}, '{"a": 1}'),
            "copied": self.folder("robustness_reports", "b2", {"job_id": "j2", "backend_job_id": "b2", "assessment_id": lacking.pk}, '{"b": 2}'),
            "orphan": self.folder("analysis_reports", "j3", {"job_id": "j3"}, "{}"),
            "unreadable": self.folder("robustness_reports", "b4", {"assessment_id": unreadable.pk}, "not json"),
        }

        output = self.run_command()
        self.assertIn("1 in the database, 1 copied to the database, 1 no assessment, 1 kept, unreadable", output)
        self.assertTrue(all(folder.exists() for folder in folders.values()))
        lacking.refresh_from_db()
        self.assertIsNone(lacking.results)

        self.run_command("--apply")
        self.assertEqual([name for name, folder in folders.items() if folder.exists()], ["unreadable"])
        self.assertFalse((self.base_dir / "analysis_reports").exists())
        lacking.refresh_from_db()
        self.assertEqual((lacking.status, lacking.results), (Assessment.Status.COMPLETED, {"b": 2}))
        self.assertEqual(lacking.input_data, {"job_id": "j2", "backend_job_id": "b2"})
        in_db.refresh_from_db()
        self.assertEqual(in_db.input_data, {"job_id": "j1", "backend_job_id": "b1"})


class AssessmentEditTests(PermissionFixture):
    def parent(self, assessment_type):
        return Assessment.objects.create(project=self.project, assessment_type=assessment_type, input_data={"config": {}})

    def test_a_parent_from_another_project_is_not_versioned(self):
        other = Project.objects.create(name="Editor's own", creator=self.editor)
        parent = self.parent(Assessment.AssessmentType.CODE_ANALYSIS)
        self.client.force_login(self.editor)
        with patch("code_analysis.views.threading.Thread"):
            self.client.post(reverse("code_analysis:processing"), {
                "source_type": "GitHub Repository", "repo_url": "https://github.com/example/repo",
                "project_id": other.pk, "parent_assessment_id": parent.pk,
            })

        created = Assessment.objects.get(project=other)
        self.assertIsNone(created.parent_assessment)
        self.assertEqual(created.version, 1)

    def test_a_robustness_form_error_keeps_editing(self):
        parent = self.parent(Assessment.AssessmentType.ROBUSTNESS)
        self.client.force_login(self.owner)
        response = self.client.post(reverse("robustness:config_input"), {
            "project_id": self.project.pk, "parent_assessment_id": parent.pk,
        })

        self.assertEqual(response.context["mode"], "edit")
        self.assertEqual(response.context["parent_assessment_id"], parent.pk)
        self.assertContains(response, "Please select a YAML configuration file")


class AiActFindingsSummaryTests(TestCase):
    def summary(self, track_results):
        from trustworthiness.views import _ai_act_findings_summary
        return _ai_act_findings_summary({"roles": [], "track_results": track_results})

    def test_one_track(self):
        self.assertEqual(
            self.summary({"ai_system": {"risk_category": "transparency_risk", "role": "provider"}}),
            "AI System: Transparency (Limited) Risk (Provider)",
        )

    def test_both_tracks_in_track_order(self):
        self.assertEqual(
            self.summary({
                "gpai_model": {"risk_category": "systemic_risk", "role": "provider"},
                "ai_system": {"risk_category": "high_risk", "role": "deployer"},
            }),
            "AI System: High Risk (Deployer) · GPAI Model: Systemic Risk (Provider)",
        )

    def test_undetermined_risk_and_missing_role(self):
        self.assertEqual(
            self.summary({"ai_system": {"risk_category": None, "role": None}}),
            "AI System: Not yet determined",
        )

    def test_no_results(self):
        self.assertEqual(self.summary({}), "-")
        from trustworthiness.views import _ai_act_findings_summary
        self.assertEqual(_ai_act_findings_summary(None), "-")


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
