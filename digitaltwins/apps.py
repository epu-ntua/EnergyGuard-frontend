from django.apps import AppConfig


class DigitaltwinsConfig(AppConfig):
    name = 'digitaltwins'

    def ready(self):
        from .ber import signals  # noqa: F401  (registers the receivers)
