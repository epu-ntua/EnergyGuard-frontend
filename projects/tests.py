from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from projects.models import Project, ProjectCollaborator


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


class ProjectTypeStyleTests(TestCase):
    def test_every_type_has_its_own_icon(self):
        owner = make_user("styler@example.com")
        icons = {
            Project(name="p", creator=owner, project_type=value).type_style["icon"]
            for value in Project.ProjectType.values
        }
        self.assertEqual(len(icons), len(Project.ProjectType.values))
        self.assertNotIn("fa-folder", icons)
