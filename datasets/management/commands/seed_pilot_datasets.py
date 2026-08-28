"""
Create (or refresh) a Dataset row per pilot partner, pointing at the daily
export the data management server publishes to MinIO.

    python manage.py seed_pilot_datasets
    python manage.py seed_pilot_datasets --partner REA

The rows carry no per-user object: every user sees the same
``pilot_datasets/<PARTNER>/<PARTNER>.csv.gz`` key, which is what makes the
JupyterHub side a read-only mount rather than a copy.
"""

from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datasets.models import Dataset
from datasets.services.pilot import PILOT_PARTNERS, pilot_object_key


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
            dataset, created = Dataset.objects.update_or_create(
                name=f"{name} Pilot Data",
                defaults={
                    "description": (
                        f"Raw sensor time series for the {name} pilot, refreshed "
                        f"daily from the EnergyGuard data lake."
                    ),
                    "label": Dataset.Label.IOT_SENSORS_MONITORING,
                    "source": Dataset.Source.ENERGYGUARD_DL,
                    "status": Dataset.Status.APPROVED,
                    "visibility": options["visible"],
                    "size_gb": Decimal("0.01"),
                    "bucket_name": settings.OBJECT_STORAGE_BUCKET,
                    "data_file": pilot_object_key(name),
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
