"""Regression tests for dataset object-level access control.

These endpoints used to resolve a Dataset with a bare `get_object_or_404(Dataset,
pk=...)`. Because ids are sequential, any authenticated user could walk them and
read every private and under-review dataset on the platform. Each test below
fails against that older behaviour.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from datasets.models import Dataset
from projects.models import Project, ProjectCollaborator

User = get_user_model()


def make_user(email, **extra):
    return User.objects.create_user(email=email, password="pw-for-tests", **extra)


def make_dataset(name, publisher, *, visibility):
    return Dataset.objects.create(
        name=name,
        publisher=publisher,
        visibility=visibility,
        size_gb=Decimal("1.00"),
        data_file=f"user_x/{name}/data.csv",
        bucket_name="energyguard-datasets",
    )


class DatasetVisibilityQuerySetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner@example.com")
        cls.other = make_user("other@example.com")
        cls.staff = make_user("staff@example.com", is_staff=True)

        cls.private = make_dataset("private-set", cls.owner, visibility=False)
        cls.public = make_dataset("public-set", cls.owner, visibility=True)
        cls.platform = Dataset.objects.create(
            name="platform-set", publisher=None, visibility=True,
            size_gb=Decimal("1.00"), bucket_name="energyguard-datasets",
        )

    def test_owner_sees_own_private_dataset(self):
        visible = Dataset.objects.visible_to(self.owner)
        self.assertIn(self.private, visible)

    def test_other_user_does_not_see_someone_elses_private_dataset(self):
        visible = Dataset.objects.visible_to(self.other)
        self.assertNotIn(self.private, visible)
        self.assertIn(self.public, visible)
        self.assertIn(self.platform, visible)

    def test_staff_sees_everything(self):
        self.assertIn(self.private, Dataset.objects.visible_to(self.staff))

    def test_is_editable_by_is_not_granted_by_public_visibility(self):
        self.assertTrue(self.public.is_editable_by(self.owner))
        self.assertFalse(self.public.is_editable_by(self.other))
        # A platform dataset has no publisher, so nobody edits it through the UI.
        self.assertFalse(self.platform.is_editable_by(self.owner))


class DatasetEndpointScopingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner2@example.com")
        cls.other = make_user("other2@example.com")
        cls.private = make_dataset("secret-pilot-data", cls.owner, visibility=False)

    def setUp(self):
        self.client.force_login(self.other)

    def test_download_of_another_users_private_dataset_is_404(self):
        response = self.client.get(reverse("dataset_download", args=[self.private.pk]))
        self.assertEqual(response.status_code, 404)

    def test_preview_of_another_users_private_dataset_is_404(self):
        response = self.client.get(reverse("dataset_preview", args=[self.private.pk]))
        self.assertEqual(response.status_code, 404)

    def test_details_of_another_users_private_dataset_redirects_away(self):
        response = self.client.get(reverse("dataset_details", args=[self.private.pk]))
        self.assertEqual(response.status_code, 302)

    def test_owner_still_reaches_their_own_private_dataset(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dataset_details", args=[self.private.pk]))
        self.assertEqual(response.status_code, 200)


class DatasetRunProjectPermissionTests(TestCase):
    """dataset_run calls project.datasets.add(), so it writes to the project.

    It used to take project_id straight from the request body with no check at
    all, letting anyone attach any dataset to anyone's project.
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("proj-owner@example.com")
        cls.viewer = make_user("viewer@example.com")
        cls.editor = make_user("editor@example.com")
        cls.stranger = make_user("stranger@example.com")

        # Public on purpose: read access must not imply write access.
        cls.project = Project.objects.create(
            name="Public project", creator=cls.owner, visibility=True,
        )
        ProjectCollaborator.objects.create(
            project=cls.project, collaborator=cls.viewer,
            permission_level=ProjectCollaborator.Permission.VIEW,
        )
        ProjectCollaborator.objects.create(
            project=cls.project, collaborator=cls.editor,
            permission_level=ProjectCollaborator.Permission.EDIT,
        )
        cls.dataset = make_dataset("shared-set", cls.owner, visibility=True)

    def _run(self, user):
        self.client.force_login(user)
        return self.client.post(
            reverse("dataset_run", args=[self.dataset.pk]),
            data='{"project_id": %d}' % self.project.pk,
            content_type="application/json",
        )

    def test_stranger_cannot_attach_a_dataset_to_a_public_project(self):
        self.assertEqual(self._run(self.stranger).status_code, 403)
        self.assertEqual(self.project.datasets.count(), 0)

    def test_view_only_collaborator_cannot_attach(self):
        self.assertEqual(self._run(self.viewer).status_code, 403)
        self.assertEqual(self.project.datasets.count(), 0)

    def test_project_can_edit_reflects_permission_level(self):
        self.assertTrue(self.project.can_edit(self.owner))
        self.assertTrue(self.project.can_edit(self.editor))
        self.assertFalse(self.project.can_edit(self.viewer))
        self.assertFalse(self.project.can_edit(self.stranger))

    def test_public_visibility_does_not_grant_delete(self):
        self.assertTrue(self.project.can_delete(self.owner))
        self.assertFalse(self.project.can_delete(self.editor))
        self.assertFalse(self.project.can_delete(self.stranger))
