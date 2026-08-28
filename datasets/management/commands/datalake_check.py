"""
Connectivity and sanity check for the pilot data lake.

    python manage.py datalake_check                     # probe every partner
    python manage.py datalake_check --partner RDN       # one partner, show rows
    python manage.py datalake_check --partner RDN --download   # full export size
"""

import time

from django.core.management.base import BaseCommand, CommandError

from datasets.services.datalake import (
    PARTNER_DATABASES,
    DataLakeError,
    fetch_raw_preview,
    stream_raw_csv,
)


class Command(BaseCommand):
    help = "Check connectivity to the EnergyGuard pilot data lake."

    def add_arguments(self, parser):
        parser.add_argument(
            "--partner",
            help="Only check this partner (default: all).",
        )
        parser.add_argument(
            "--rows",
            type=int,
            default=3,
            help="How many preview rows to print (default: 3).",
        )
        parser.add_argument(
            "--download",
            action="store_true",
            help="Stream the full raw export and report its size, without saving it.",
        )

    def handle(self, *args, **options):
        partner = options["partner"]
        if partner:
            key = partner.strip().upper()
            if key not in PARTNER_DATABASES:
                raise CommandError(
                    f"Unknown partner '{partner}'. "
                    f"Valid options: {', '.join(PARTNER_DATABASES)}."
                )
            partners = [key]
        else:
            partners = list(PARTNER_DATABASES)

        failures = 0
        for name in partners:
            if not self._check_partner(name, options):
                failures += 1

        self.stdout.write("")
        checked = len(partners)
        if failures:
            self.stdout.write(
                self.style.WARNING(f"{checked - failures}/{checked} partners reachable.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"All {checked} partner(s) reachable.")
            )

    def _check_partner(self, partner: str, options) -> bool:
        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"{partner} ({PARTNER_DATABASES[partner]})")
        )

        started = time.monotonic()
        try:
            headers, rows = fetch_raw_preview(partner, options["rows"])
        except DataLakeError as exc:
            self.stdout.write(self.style.ERROR(f"  FAILED: {exc}"))
            return False

        elapsed = time.monotonic() - started
        self.stdout.write(f"  preview OK in {elapsed:.2f}s — {len(rows)} row(s)")
        self.stdout.write(f"  columns: {', '.join(headers)}")
        for row in rows:
            self.stdout.write(f"    {row}")
        if not rows:
            self.stdout.write(self.style.WARNING("  table is empty"))

        if options["download"]:
            started = time.monotonic()
            total = 0
            lines = 0
            try:
                for block in stream_raw_csv(partner):
                    total += len(block)
                    lines += block.count(b"\n")
            except DataLakeError as exc:
                self.stdout.write(self.style.ERROR(f"  EXPORT FAILED: {exc}"))
                return False
            elapsed = time.monotonic() - started
            self.stdout.write(
                f"  full export OK in {elapsed:.2f}s — "
                f"{total / 1024 / 1024:.2f} MB, ~{max(lines - 1, 0)} data rows"
            )

        return True
