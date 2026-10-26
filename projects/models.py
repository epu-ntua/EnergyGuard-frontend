from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.functional import cached_property

from core.models import TimeStampedModel


def _is_authenticated(user):
    return bool(user and getattr(user, 'is_authenticated', False))


class ProjectQuerySet(models.QuerySet):
    def member_of(self, user):
        """Projects `user` created or collaborates on."""
        if not _is_authenticated(user):
            return self.none()
        return self.filter(Q(creator=user) | Q(collaborators=user)).distinct()

    def visible_to(self, user):
        """Projects `user` may READ: public ones plus their own.

        The single source of the read rule - `Project.is_accessible_by` and
        every list that names projects go through this, so a change to who can
        see a project (e.g. team-based access) only has to be made here.
        """
        if not _is_authenticated(user):
            return self.filter(visibility=True)
        return self.filter(
            Q(visibility=True) | Q(creator=user) | Q(collaborators=user)
        ).distinct()


# Icon and phoenix theme colour per project type, shared by every page that
# lists projects (server-rendered via `type_style`, or in JSON for JS lists).
_TYPE_STYLES = {
    'ai_model': ('fa-brain', 'purple'),
    'ai_service': ('fa-robot', 'indigo'),
    'application': ('fa-desktop', 'cyan'),
    'edge_embedded_ai': ('fa-microchip', 'turquoise'),
    'data_pipeline': ('fa-stream', 'lavender'),
    'simulation_model': ('fa-flask', 'purple-blue'),
    'ai_agent_system': ('fa-diagram-project', 'teal'),
}
_DEFAULT_TYPE_STYLE = ('fa-folder', 'gray-600')


class Project(TimeStampedModel):
    class ProjectType(models.TextChoices):
        AI_MODEL = 'ai_model', 'AI Model'
        AI_SERVICE = 'ai_service', 'AI Service'
        APPLICATION = 'application', 'Application'
        EDGE_EMBEDDED_AI = 'edge_embedded_ai', 'Edge / Embedded AI'
        DATA_PIPELINE = 'data_pipeline', 'Data Pipeline'
        SIMULATION_MODEL = 'simulation_model', 'Simulation Model'
        AI_AGENT_SYSTEM = 'ai_agent_system', 'AI Agent System'

    name = models.CharField(max_length=255)
    collaborators = models.ManyToManyField(settings.AUTH_USER_MODEL, through='ProjectCollaborator', related_name='collaborator_projects')
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='creator_projects')
    project_type = models.CharField(max_length=20, choices=ProjectType, default=ProjectType.AI_MODEL)
    description = models.TextField(blank=True)
    visibility = models.BooleanField(default=False)

    objects = ProjectQuerySet.as_manager()

    def __str__(self):
        return self.name

    @cached_property
    def type_style(self):
        """`icon`, `color` and a 12% tint `bg` for this project's type."""
        icon, colour = _TYPE_STYLES.get(self.project_type, _DEFAULT_TYPE_STYLE)
        color = f'var(--phoenix-{colour})'
        return {
            'icon': icon,
            'color': color,
            'bg': f'color-mix(in srgb, {color} 12%, transparent)',
        }

    def is_accessible_by(self, user):
        """READ access. A public project is readable by everyone.

        This must not be used to gate writes - see `can_edit`. Kept under its
        original name because other apps call it as a read check.
        """
        return Project.objects.visible_to(user).filter(pk=self.pk).exists()

    # Alias that says what it actually means, for new call sites.
    can_view = is_accessible_by

    def can_edit(self, user):
        """WRITE access: the creator, or a collaborator granted EDIT.

        Public visibility deliberately grants nothing here - it makes a project
        readable, not writable. `ProjectCollaborator.permission_level` was
        declared but never enforced anywhere; this is where it takes effect.
        """
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if self.creator_id == user.id:
            return True
        return ProjectCollaborator.objects.filter(
            project=self, collaborator=user, permission_level=ProjectCollaborator.Permission.EDIT,
        ).exists()

    def can_delete(self, user):
        """Only the creator may delete a project or its experiments wholesale."""
        return bool(user and getattr(user, 'is_authenticated', False) and self.creator_id == user.id)

    class Meta:
        db_table = 'project'
        verbose_name = 'Project'
        verbose_name_plural = 'Projects'
        ordering = ["-created_at"]
        indexes = [models.Index(fields=['name']),]


class Experiment(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="experiments")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_experiments",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    mlflow_experiment_id = models.CharField(max_length=64, blank=True, default="")
    description = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name or f"Experiment {self.pk}"

    class Meta:
        db_table = "experiment"
        verbose_name = "Experiment"
        verbose_name_plural = "Experiments"
        ordering = ["-created_at"]


# Intermediate model for collaborators - projects with extra fields
class ProjectCollaborator(TimeStampedModel):
    class Permission(models.TextChoices):
        VIEW = 'view', 'Only View'
        EDIT = 'edit', 'Can Edit'

    collaborator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    permission_level = models.CharField(max_length=4, choices=Permission, default=Permission.VIEW)

    class Meta:
        db_table = 'project_collaborator'
        verbose_name = 'Project Collaborator'
        verbose_name_plural = 'Project Collaborators'
        # Prevent multiple associations between the same instances
        constraints = [
            models.UniqueConstraint(
                fields=["collaborator", "project"], name="unique_person_project"
            )
        ]
