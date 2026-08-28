"""
Create (or refresh) a Dataset row per pilot partner, pointing at the daily
export the data management server publishes to MinIO.

    python manage.py seed_pilot_datasets
    python manage.py seed_pilot_datasets --partner REA

The rows carry no per-user object: every user sees the same
``pilot_datasets/<PARTNER>/<PARTNER>.csv.gz`` key, which is what makes the
JupyterHub side a read-only mount rather than a copy.

Pilot status comes from that key prefix alone — nothing is written to
``metadata``, which the details page renders as a table of dataset features.

Idempotent: rows are matched on name, so re-running refreshes sizes in place.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from datasets.models import Dataset
from datasets.services.pilot import PILOT_PARTNERS, pilot_object_key, pilot_object_size

# size_gb is DecimalField(decimal_places=2) with a 0.01 floor, so anything below
# ~10 MB pins to the minimum. Store the closest legal value; the byte count is
# reported in the command output.
MIN_SIZE_GB = Decimal("0.01")
BYTES_PER_GB = Decimal(1024 ** 3)


def _size_gb(size_bytes: int | None) -> Decimal:
    if not size_bytes:
        return MIN_SIZE_GB
    gb = (Decimal(size_bytes) / BYTES_PER_GB).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return max(gb, MIN_SIZE_GB)


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

        missing = []
        for name in partners:
            size_bytes = pilot_object_size(name)
            if size_bytes is None:
                missing.append(name)

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
                    "size_gb": _size_gb(size_bytes),
                    "bucket_name": settings.OBJECT_STORAGE_BUCKET,
                    "data_file": pilot_object_key(name),
                },
            )
            # Older rows carried a {"pilot_partner": ...} marker here. The details
            # page renders metadata as a table of dataset features, so the marker
            # showed up as a bogus feature row. Strip it, keeping any real
            # feature documentation that has since been added alongside it.
            if isinstance(dataset.metadata, dict) and "pilot_partner" in dataset.metadata:
                remaining = {
                    k: v for k, v in dataset.metadata.items() if k != "pilot_partner"
                }
                dataset.metadata = remaining or None
                dataset.save(update_fields=["metadata"])

            verb = "created" if created else "updated"
            if size_bytes is None:
                size_note = self.style.WARNING("NOT EXPORTED YET")
            else:
                size_note = f"{size_bytes:,} bytes -> {dataset.size_gb} GB"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{verb} #{dataset.id} '{dataset.name}' -> "
                    f"{dataset.bucket_name}/{dataset.data_file}"
                )
            )
            self.stdout.write(f"    size:     {size_note}")
            self.stdout.write(
                f"    preview:  /datasets/dataset/{dataset.id}/preview/\n"
                f"    download: /datasets/dataset/{dataset.id}/download/"
            )

        if missing:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(missing)} partner(s) have no export in MinIO yet: "
                    f"{', '.join(missing)}. Their rows exist but preview and "
                    f"download will return 404 until the export runs."
                )
            )
