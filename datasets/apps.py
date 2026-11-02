from django.apps import AppConfig


class DatasetsConfig(AppConfig):
    name = 'datasets'

    def ready(self):
        from . import signals  # noqa: F401
