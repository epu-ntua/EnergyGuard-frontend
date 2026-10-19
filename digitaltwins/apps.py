from django.apps import AppConfig


class DigitaltwinsConfig(AppConfig):
    name = 'digitaltwins'

    def ready(self):
        from . import checks, signals  # noqa: F401  (registers the checks and receivers)
        from .ber import signals as ber_signals  # noqa: F401
        # Each twin registers what it adds to the shared run and export code.
        from .ber import exports as ber_exports  # noqa: F401
        from .ciemat import runs as ciemat_runs  # noqa: F401
        from .engreen import runs as engreen_runs  # noqa: F401
        from .rdn import exports as rdn_exports  # noqa: F401
        from .runs import exports as run_exports  # noqa: F401
