"""System checks for the digitaltwins app."""

from django.conf import settings
from django.core.checks import Warning, register

# The bucket production keeps the twins' results in.
PRODUCTION_SIMULATIONS_BUCKET = 'dt-results'


@register()
def development_uses_its_own_results_bucket(app_configs, **kwargs):
    """A development machine writing to production's results bucket can overwrite,
    and on delete remove, a real user's result: RDN and BER results are keyed by
    row ids, which every database starts from 1."""
    if settings.DEBUG and settings.OBJECT_STORAGE_BUCKET_SIMULATIONS == PRODUCTION_SIMULATIONS_BUCKET:
        return [Warning(
            f"OBJECT_STORAGE_BUCKET_SIMULATIONS is production's bucket '{PRODUCTION_SIMULATIONS_BUCKET}' "
            "while DEBUG is on.",
            hint="Locally, set OBJECT_STORAGE_BUCKET_SIMULATIONS=dt-results-dev and DT_EXPORT_NAME_PREFIX=dev- in .env.",
            id='digitaltwins.W001',
        )]
    return []
