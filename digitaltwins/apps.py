from django.apps import AppConfig


class DigitaltwinsConfig(AppConfig):
    name = 'digitaltwins'

    def ready(self):
        from . import checks, signals  # noqa: F401  (registers the checks and receivers)
        from .ber import signals as ber_signals  # noqa: F401
