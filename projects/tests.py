import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from projects.models import Experiment, Project, ProjectCollaborator
from projects.services.mlflow_client import MlflowClientError, delete_mlflow_user, purge_deleted_experiment
from projects.signals import MLFLOW_ALREADY_REMOVED
from projects.tasks import discard_mlflow_experiment


def make_user(email):
    return get_user_model().objects.create_user(email=email, password="pw-for-tests")


class ProjectVisibilityTests(TestCase):
    """`visible_to` is the read rule; `is_accessible_by` must agree with it."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner@example.com")
        cls.collab = make_user("collab@example.com")
        cls.stranger = make_user("stranger@example.com")
        cls.public = Project.objects.create(name="Public", creator=cls.owner, visibility=True)
        cls.private = Project.objects.create(name="Private", creator=cls.owner, visibility=False)
        ProjectCollaborator.objects.create(collaborator=cls.collab, project=cls.private)

    def test_visible_to(self):
        cases = [
            (self.owner, {self.public, self.private}),
            (self.collab, {self.public, self.private}),
            (self.stranger, {self.public}),
            (AnonymousUser(), {self.public}),
        ]
        for user, expected in cases:
            with self.subTest(user=user):
                self.assertEqual(set(Project.objects.visible_to(user)), expected)
                for project in (self.public, self.private):
                    self.assertEqual(project.is_accessible_by(user), project in expected)

    def test_visible_to_has_no_duplicates(self):
        # Creator and collaborator at once must not yield the row twice.
        ProjectCollaborator.objects.create(collaborator=self.owner, project=self.public)
        self.assertEqual(Project.objects.visible_to(self.owner).count(), 2)

    def test_member_of_excludes_foreign_public_projects(self):
        self.assertEqual(set(Project.objects.member_of(self.collab)), {self.private})
        self.assertEqual(set(Project.objects.member_of(self.stranger)), set())
        self.assertEqual(set(Project.objects.member_of(AnonymousUser())), set())


class ProjectsListJsonOrderingTests(TestCase):
    # Same columns, in the same order, as the table in projects-list.html.
    COLUMNS = ["name", "description", "created_at", "updated_at", "project_type", "id"]

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("lister@example.com")
        # Start-date order differs from both name order and insertion (id)
        # order, so only a real created_at sort yields the expected list.
        for day, name in ((3, "Bravo"), (1, "Charlie"), (2, "Alpha")):
            project = Project.objects.create(name=name, creator=cls.owner)
            Project.objects.filter(pk=project.pk).update(
                created_at=datetime(2026, 1, day, tzinfo=timezone.utc)
            )

    def test_sorting_start_date_column_orders_by_created_at(self):
        self.client.force_login(self.owner)
        params = {"scope": "my", "draw": 1, "start": 0, "length": 15,
                  "order[0][column]": 2, "order[0][dir]": "asc"}
        for i, data in enumerate(self.COLUMNS):
            params[f"columns[{i}][data]"] = data
            params[f"columns[{i}][name]"] = ""
        response = self.client.get(reverse("projects_list_json"), params)
        names = [row["name"] for row in response.json()["data"]]
        self.assertEqual(names, ["Charlie", "Alpha", "Bravo"])


class ProjectTypeStyleTests(TestCase):
    def test_every_type_has_its_own_icon(self):
        owner = make_user("styler@example.com")
        icons = {
            Project(name="p", creator=owner, project_type=value).type_style["icon"]
            for value in Project.ProjectType.values
        }
        self.assertEqual(len(icons), len(Project.ProjectType.values))
        self.assertNotIn("fa-folder", icons)


def make_user_without_mlflow(email):
    with patch("projects.services.mlflow_client.create_mlflow_user"):
        return make_user(email)


class MlflowDeleteSignalTests(TestCase):
    """Deletes that bypass the views (the account CASCADE above all) clean up MLflow on the qcluster."""

    def setUp(self):
        self.owner = make_user_without_mlflow("mlflow-owner@example.com")
        self.other = make_user_without_mlflow("mlflow-other@example.com")
        own = Project.objects.create(name="Own", creator=self.owner)
        foreign = Project.objects.create(name="Foreign", creator=self.other)
        Experiment.objects.create(project=own, creator=self.owner, mlflow_experiment_id="11")
        Experiment.objects.create(project=own, creator=self.owner, mlflow_experiment_id="")
        Experiment.objects.create(project=foreign, creator=self.owner, mlflow_experiment_id="22")
        self.untouched = Experiment.objects.create(project=foreign, creator=self.other, mlflow_experiment_id="33")

    def queued(self, async_task):
        return sorted((call.args[0], tuple(call.kwargs.values())) for call in async_task.call_args_list)

    @patch("projects.signals.async_task")
    def test_account_delete_queues_its_experiments_and_mlflow_user(self, async_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.owner.delete()
        self.assertEqual(self.queued(async_task), [
            ("projects.tasks.discard_mlflow_experiment", ("11",)),
            ("projects.tasks.discard_mlflow_experiment", ("22",)),
            ("projects.tasks.discard_mlflow_user", ("mlflow-owner@example.com",)),
        ])
        self.assertTrue(Experiment.objects.filter(pk=self.untouched.pk).exists())

    @patch("projects.signals.async_task")
    def test_experiment_cleaned_by_the_view_is_not_queued_again(self, async_task):
        setattr(self.untouched, MLFLOW_ALREADY_REMOVED, True)
        with self.captureOnCommitCallbacks(execute=True):
            self.untouched.delete()
        async_task.assert_not_called()

    @patch("projects.signals.async_task")
    def test_rolled_back_delete_queues_nothing(self, async_task):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    self.owner.delete()
                    raise RuntimeError
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])
        async_task.assert_not_called()


@patch("projects.tasks.purge_deleted_experiment")
@patch("projects.tasks.delete_experiment")
@patch("projects.tasks.update_experiment_name")
@patch("projects.tasks.delete_all_experiment_tags")
@patch("projects.tasks.find_any_run_id", return_value="run-1")
@patch("projects.tasks.delete_artifacts_from_object_storage")
class DiscardMlflowExperimentTaskTests(SimpleTestCase):
    def test_deletes_and_purges_through_one_of_its_runs(self, artifacts, find_run, tags, rename, delete, purge):
        discard_mlflow_experiment(mlflow_experiment_id="7")
        artifacts.assert_called_once_with("7")
        delete.assert_called_once_with("7")
        purge.assert_called_once_with("7", "run-1")
        tags.assert_not_called()

    def test_without_runs_empties_its_tags_and_leaves_it_in_the_trash(self, artifacts, find_run, tags, rename, delete, purge):
        find_run.return_value = None
        with self.assertLogs("projects.tasks", "WARNING"):
            discard_mlflow_experiment(mlflow_experiment_id="7")
        tags.assert_called_once_with("7")
        delete.assert_called_once_with("7")
        purge.assert_not_called()

    def test_failed_run_lookup_still_deletes_but_does_not_purge(self, artifacts, find_run, tags, rename, delete, purge):
        find_run.side_effect = MlflowClientError("boom")
        with self.assertLogs("projects.tasks", "ERROR"):
            discard_mlflow_experiment(mlflow_experiment_id="7")
        tags.assert_not_called()
        delete.assert_called_once_with("7")
        purge.assert_not_called()

    def test_failed_delete_is_logged_and_skips_the_purge(self, artifacts, find_run, tags, rename, delete, purge):
        delete.side_effect = MlflowClientError("boom")
        with self.assertLogs("projects.tasks", "ERROR"):
            discard_mlflow_experiment(mlflow_experiment_id="7")
        purge.assert_not_called()


class MlflowClientDeletionTests(SimpleTestCase):
    def test_purge_refuses_to_run_without_a_run_id(self):
        # The server would purge every deleted run on it
        with patch("projects.services.mlflow_client._request") as request:
            with self.assertRaises(ValueError):
                purge_deleted_experiment("7", "")
        request.assert_not_called()

    def test_purge_raises_on_a_partial_failure(self):
        response = {"deleted_experiments": [], "failed_experiments": [{"experiment_id": "7", "error": "x"}]}
        with patch("projects.services.mlflow_client._request", return_value=response):
            with self.assertRaises(MlflowClientError):
                purge_deleted_experiment("7", "run-1")

    def test_delete_user_ignores_only_an_unknown_user(self):
        unknown = MlflowClientError('MLflow DELETE /api/2.0/mlflow/users failed with 404: {"detail":"User not found"}')
        with patch("projects.services.mlflow_client._request", side_effect=unknown):
            delete_mlflow_user("gone@example.com")

        moved = MlflowClientError("MLflow DELETE /api/2.0/mlflow/users failed with 404: <h1>Not Found</h1>")
        with patch("projects.services.mlflow_client._request", side_effect=moved):
            with self.assertRaises(MlflowClientError):
                delete_mlflow_user("gone@example.com")


@patch("projects.signals.async_task")
@patch("projects.views.experiments.mlflow_purge_deleted_experiment")
@patch("projects.views.experiments.mlflow_delete_experiment")
@patch("projects.views.experiments.mlflow_update_experiment_name")
@patch("projects.views.experiments.mlflow_find_any_run_id", return_value="run-1")
@patch("projects.views.experiments.mlflow_delete_artifacts_from_object_storage")
class DeleteProjectViewMlflowTests(TestCase):
    def setUp(self):
        self.owner = make_user_without_mlflow("view-owner@example.com")
        self.project = Project.objects.create(name="P", creator=self.owner)
        Experiment.objects.create(project=self.project, creator=self.owner, mlflow_experiment_id="7")
        self.client.force_login(self.owner)

    def delete(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("delete_project", kwargs={"project_id": self.project.pk}))

    def test_purges_in_the_request_and_queues_nothing(self, artifacts, find_run, rename, delete, purge, async_task):
        response = self.delete()
        self.assertRedirects(response, reverse("projects_list"), fetch_redirect_response=False)
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        purge.assert_called_once_with("7", "run-1")
        async_task.assert_not_called()

    def test_failed_purge_still_deletes_the_project(self, artifacts, find_run, rename, delete, purge, async_task):
        purge.side_effect = MlflowClientError("boom")
        with self.assertLogs("projects.views.experiments", "ERROR"):
            self.delete()
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        async_task.assert_not_called()

    def test_failed_run_lookup_stops_the_delete(self, artifacts, find_run, rename, delete, purge, async_task):
        find_run.side_effect = MlflowClientError("boom")
        with self.assertLogs("projects.views.experiments", "ERROR"):
            self.delete()
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())
        delete.assert_not_called()


RUN = {
    "info": {"run_id": "r1", "status": "FINISHED", "start_time": 1, "end_time": 2},
    "data": {"metrics": [{"key": "rmse", "value": 0.5}]},
}


@patch("projects.views.experiments.list_registered_model_versions_for_run", return_value=[])
@patch("projects.views.experiments.list_experiment_runs", return_value=[RUN])
class EvalResultsViewTests(TestCase):
    """The endpoint behind the metrics charts on the project details page."""

    def setUp(self):
        self.owner = make_user_without_mlflow("eval-owner@example.com")
        self.project = Project.objects.create(name="P", creator=self.owner)
        self.experiment = Experiment.objects.create(
            project=self.project, creator=self.owner, name="Exp", mlflow_experiment_id="7"
        )
        self.client.force_login(self.owner)

    def url(self, experiment_id=None):
        return reverse("eval_results", kwargs={
            "project_id": self.project.pk,
            "experiment_id": experiment_id or self.experiment.pk,
        })

    def test_charts_skip_the_registered_models(self, runs, model_versions):
        response = self.client.get(self.url(), {"include_models": "0"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["all_run_metrics_chronological"],
            [{"run_id": "r1", "metrics": {"rmse": 0.5}}],
        )
        model_versions.assert_not_called()

    def test_registered_models_are_included_by_default(self, runs, model_versions):
        self.client.get(self.url())
        model_versions.assert_called_once()

    def test_unknown_experiment_answers_json_not_a_redirect(self, runs, model_versions):
        response = self.client.get(self.url(experiment_id=self.experiment.pk + 1000))
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_mlflow_failure_is_logged_but_not_sent_to_the_browser(self, runs, model_versions):
        runs.side_effect = MlflowClientError("boom: MLflow response body")
        with self.assertLogs("projects.views.experiments", "WARNING") as logs:
            response = self.client.get(self.url(), {"include_models": "0"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("MLflow response body", logs.output[0])
        self.assertNotIn("MLflow response body", response.json()["error"])

    def test_non_finite_metrics_are_dropped(self, runs, model_versions):
        run = {**RUN, "data": {"metrics": [
            {"key": "rmse", "value": 0.5},
            {"key": "loss", "value": float("nan")},
            {"key": "grad", "value": float("inf")},
        ]}}
        runs.return_value = [run]
        response = self.client.get(self.url(), {"include_models": "0"})
        # Parsed by the strict json module, as a browser would
        body = json.loads(response.content, parse_constant=lambda c: self.fail(f"{c} in JSON"))
        self.assertEqual(body["all_run_metrics_chronological"][0]["metrics"], {"rmse": 0.5})

    def test_details_page_offers_each_experiment_to_the_charts(self, runs, model_versions):
        response = self.client.get(reverse("project_details", kwargs={"project_id": self.project.pk}))
        self.assertContains(response, f'data-url="{self.url()}?include_models=0"')
        self.assertNotContains(response, "mock data")
