"""
Create (or refresh) a Dataset row per pilot partner, pointing at the daily
export the data management server publishes to MinIO.

    python manage.py seed_pilot_datasets
    python manage.py seed_pilot_datasets --partner REA

The rows carry no per-user object: every user sees the same
``pilot_datasets/<PARTNER>/<PARTNER>.csv.gz`` key, which is what makes the
JupyterHub side a read-only mount rather than a copy.
"""

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datasets.models import Dataset
from datasets.services import get_object_size, object_exists
from datasets.services.pilot import PILOT_PARTNERS, pilot_description, pilot_object_key


def _size_gb(bucket_name: str, object_key: str) -> Decimal:
    """Same bytes -> GB conversion used for user-uploaded datasets (see views/upload.py)."""
    size_bytes = get_object_size(bucket_name=bucket_name, object_key=object_key)
    size_gb = (Decimal(size_bytes) / Decimal(1024 ** 3)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return max(size_gb, Decimal("0.01"))


class Command(BaseCommand):
    help = "Create a Dataset row for each pilot partner backed by its MinIO export."

    def add_arguments(self, parser):
        parser.add_argument("--partner", help="Only seed this partner (default: all).")
        parser.add_argument(
            "--visible",
            action="store_true",
            help="Mark the seeded datasets as publicly visible.",
        )

    def handle(self, *args, **options):
        partner = options["partner"]
        if partner:
            name = partner.strip().upper()
            if name not in PILOT_PARTNERS:
                raise CommandError(
                    f"Unknown partner '{partner}'. "
                    f"Valid options: {', '.join(PILOT_PARTNERS)}."
                )
            partners = [name]
        else:
            partners = list(PILOT_PARTNERS)

        for name in partners:
            bucket_name = settings.OBJECT_STORAGE_BUCKET
            object_key = pilot_object_key(name)

            if not object_exists(bucket_name=bucket_name, object_key=object_key):
                self.stderr.write(
                    self.style.WARNING(
                        f"Skipping {name}: '{object_key}' not found in bucket '{bucket_name}' yet."
                    )
                )
                Dataset.objects.filter(name=f"{name} Pilot Data").delete()
                continue

            size_gb = _size_gb(bucket_name, object_key)

            # TODO: `updated_at` (auto_now) is set to whenever this command last ran,
            # not to when the data lake actually refreshed the export. Once the daily
            # data management export exposes a real last-update timestamp (e.g. the
            # MinIO object's LastModified, or a value from the data lake API), use that
            # here instead so "Last Updated" reflects the real data freshness.
            dataset, created = Dataset.objects.update_or_create(
                name=f"{name} Pilot Data",
                defaults={
                    "description": pilot_description(name),
                    "label": Dataset.Label.IOT_SENSORS_MONITORING,
                    "source": Dataset.Source.ENERGYGUARD_DL,
                    "status": Dataset.Status.APPROVED,
                    "visibility": options["visible"],
                    "size_gb": size_gb,
                    "bucket_name": bucket_name,
                    "data_file": object_key,
                    "metadata": {"pilot_partner": name},
                },
            )
            verb = "created" if created else "updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{verb} #{dataset.id} '{dataset.name}' -> "
                    f"{dataset.bucket_name}/{dataset.data_file}"
                )
            )
            self.stdout.write(
                f"    preview:  /datasets/dataset/{dataset.id}/preview/\n"
                f"    download: /datasets/dataset/{dataset.id}/download/"
            )
