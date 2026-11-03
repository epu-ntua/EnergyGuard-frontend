from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    name = 'projects'
    label = 'experiments'

    def ready(self):
        from . import signals  # noqa: F401