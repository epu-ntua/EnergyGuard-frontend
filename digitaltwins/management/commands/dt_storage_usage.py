"""
How much object storage the digital twins' results take, and what is orphaned.

    python manage.py dt_storage_usage              # per twin
    python manage.py dt_storage_usage --by-user    # per twin and user
    python manage.py dt_storage_usage --orphans    # also list unreferenced objects

Nothing is deleted automatically, so this is how the growth is watched. Sizes
come from listing each folder once, not from one request per object. An orphan
is an object under a twin's folder that no row points to - left by a failed
clean-up (its key is also in the logs) or by a row deleted outside Django.
"""

from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.object_storage import MinioUploadError, build_minio_client
from digitaltwins.models import BerExperimentRequest, DtExport, DtRun, RdnSimulationJob

# The folders of the simulations bucket that hold the twins' results.
RESULT_FOLDERS = ('dt-runs/', 'rdn-grid/', 'ber-hydrogen/')


def _list_sizes(client, bucket, prefix):
    """{key: size} of every object under `prefix`."""
    sizes = {}
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            sizes[obj['Key']] = obj['Size']
    return sizes


def _readable(size):
    """A readable size: KB below a megabyte, so small JSON results don't read as 0."""
    if size < 1024 * 1024:
        return f'{size / 1024:,.1f} KB'
    return f'{size / (1024 * 1024):,.1f} MB'


class Command(BaseCommand):
    help = "Report the object storage used by the digital twins' results and exports."

    def add_arguments(self, parser):
        parser.add_argument('--by-user', action='store_true', help='Break the totals down per user.')
        parser.add_argument('--orphans', action='store_true', help='List the objects no row points to.')

    def handle(self, *args, **options):
        simulations = settings.OBJECT_STORAGE_BUCKET_SIMULATIONS
        datasets = settings.OBJECT_STORAGE_BUCKET
        try:
            client = build_minio_client()
            stored = {}
            for folder in RESULT_FOLDERS:
                stored.update(_list_sizes(client, simulations, folder))
            exports = DtExport.objects.select_related('user')
            exported = {}
            for user_folder in {export.result_key.split('/', 1)[0] + '/' for export in exports}:
                exported.update(_list_sizes(client, datasets, user_folder))
        except MinioUploadError as exc:
            raise CommandError(f'Could not reach object storage: {exc}') from exc

        # Every row that points at a stored object: (twin, user, key).
        referenced = [
            *((run.twin_slug, run.user.email, run.result_key)
              for run in DtRun.objects.exclude(result_key='').select_related('user')),
            *(('rdn-grid', job.user.email, job.result_key)
              for job in RdnSimulationJob.objects.exclude(result_key='').select_related('user').defer('result')),
            *(('ber-hydrogen', req.user.email, req.result_key)
              for req in BerExperimentRequest.objects.exclude(result_key='').select_related('user')),
        ]

        self._report(f'Results in {simulations}', referenced, stored, options['by_user'])
        self._report(
            f'JupyterHub copies in {datasets}',
            [(export.twin_slug, export.user.email, export.result_key) for export in exports],
            exported, options['by_user'],
        )

        orphans = sorted(set(stored) - {key for _, _, key in referenced})
        orphan_size = sum(stored[key] for key in orphans)
        self.stdout.write(f'\nOrphaned results in {simulations}: {len(orphans)} objects, {_readable(orphan_size)}')
        if options['orphans']:
            for key in orphans:
                self.stdout.write(f'  {key}  {_readable(stored[key])}')

    def _report(self, title, rows, sizes, by_user):
        totals = defaultdict(lambda: [0, 0])  # group -> [objects, bytes]
        missing = 0
        for twin, email, key in rows:
            if key not in sizes:
                missing += 1
                continue
            group = (twin, email) if by_user else (twin,)
            totals[group][0] += 1
            totals[group][1] += sizes[key]

        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{title}'))
        for group, (count, size) in sorted(totals.items(), key=lambda item: -item[1][1]):
            self.stdout.write(f"  {' / '.join(group):<60} {count:>6} objects  {_readable(size):>12}")
        total_count = sum(count for count, _ in totals.values())
        total_size = sum(size for _, size in totals.values())
        self.stdout.write(f"  {'Total':<60} {total_count:>6} objects  {_readable(total_size):>12}")
        if missing:
            self.stdout.write(self.style.WARNING(f'  {missing} rows point to objects that are not there.'))
