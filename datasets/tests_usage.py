"""Dataset <-> project usage panels.

Usage counts are shown to everyone who can see the page, but a project or
dataset is only named to a user who could open it themselves.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset
from datasets.tests_access_control import make_dataset, make_user
from projects.models import Project


def make_project(name, creator, *, visibility):
    return Project.objects.create(name=name, creator=creator, visibility=visibility)


class DatasetUsagePanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner@example.com")
        cls.viewer = make_user("viewer@example.com")
        cls.dataset = make_dataset("shared-set", cls.owner, visibility=True)
        cls.public_project = make_project("Public Proj", cls.owner, visibility=True)
        cls.private_project = make_project("Secret Proj", cls.owner, visibility=False)
        cls.viewer_project = make_project("Viewer Proj", cls.viewer, visibility=False)
        cls.dataset.projects.add(cls.public_project, cls.private_project, cls.viewer_project)

    def _get(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("dataset_details", args=[self.dataset.id]))

    def test_total_counts_every_project_across_users(self):
        response = self._get(self.viewer)
        self.assertEqual(response.context["usage_total"], 3)
        self.assertContains(response, "3 projects")
        self.assertNotContains(response, "Secret Proj")


class ProjectDatasetsPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner@example.com")
        cls.other = make_user("other@example.com")
        cls.project = make_project("Proj", cls.owner, visibility=True)
        cls.public_ds = make_dataset("public-ds", cls.other, visibility=True)
        cls.own_private_ds = make_dataset("own-private-ds", cls.owner, visibility=False)
        # Attached while public, made private by its publisher afterwards.
        cls.foreign_private_ds = make_dataset("foreign-private-ds", cls.other, visibility=False)
        cls.project.datasets.add(cls.public_ds, cls.own_private_ds, cls.foreign_private_ds)

    def test_only_visible_datasets_are_listed(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("project_details", args=[self.project.id]))
        self.assertCountEqual(
            response.context["project_datasets"], [self.public_ds, self.own_private_ds]
        )
        self.assertEqual(response.context["project_datasets_total"], 3)
        self.assertEqual(response.context["project_datasets_hidden"], 1)
        self.assertNotContains(response, "foreign-private-ds")


class DatasetsListUsageColumnTests(TestCase):
    def test_json_includes_project_count(self):
        owner = make_user("owner@example.com")
        viewer = make_user("viewer@example.com")
        dataset = make_dataset("counted", owner, visibility=True)
        dataset.projects.add(
            make_project("A", owner, visibility=False),
            make_project("B", owner, visibility=True),
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("datasets_list_json"), {"scope": "public", "draw": 1})
        row = next(r for r in response.json()["data"] if str(r[-1]) == str(dataset.id))
        self.assertEqual(int(row[6]), 2)

    def test_sorting_by_usage_pages_without_repeats(self):
        owner = make_user("sorter@example.com")
        viewer = make_user("sort-viewer@example.com")
        ids = {make_dataset(f"tied-{i}", owner, visibility=True).id for i in range(5)}

        self.client.force_login(viewer)
        seen = []
        for start in (0, 2, 4):
            response = self.client.get(reverse("datasets_list_json"), {
                "scope": "public", "draw": 1, "start": start, "length": 2,
                "order[0][column]": 6, "order[0][dir]": "asc",
            })
            seen += [int(r[-1]) for r in response.json()["data"]]
        self.assertCountEqual(seen, ids)


class DatasetsListOrderingTests(TestCase):
    def test_publisher_sorts_by_displayed_name(self):
        zed = make_user("a-zed@example.com", first_name="Zed", last_name="Last")
        amy = make_user("z-amy@example.com", first_name="Amy", last_name="First")
        nameless = make_user("m-nameless@example.com")
        viewer = make_user("viewer@example.com")
        make_dataset("by-zed", zed, visibility=True)
        make_dataset("by-amy", amy, visibility=True)
        make_dataset("by-nameless", nameless, visibility=True)
        Dataset.objects.create(
            name="by-platform", publisher=None, visibility=True,
            size_gb=Decimal("1.00"), bucket_name="energyguard-datasets",
        )

        self.client.force_login(viewer)
        response = self.client.get(reverse("datasets_list_json"), {
            "scope": "public", "draw": 1, "order[0][column]": 4, "order[0][dir]": "asc",
        })
        publishers = [r[4] for r in response.json()["data"]]
        self.assertEqual(
            publishers, ["Amy First", "EnergyGuard", "m-nameless@example.com", "Zed Last"]
        )
