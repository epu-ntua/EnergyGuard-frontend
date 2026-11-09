import datetime
import logging
import os
import subprocess
import tempfile
import traceback

import boto3
from botocore.config import Config
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.mail import mail_admins
from django.utils import timezone
from django_q.models import Task

logger = logging.getLogger(__name__)

# Task history keeps each task's arguments (emails among them) and, for a
# failure, its traceback. Long enough to debug a failure from the admin.
TASK_HISTORY_DAYS = 30

# The major version of the db service (postgres:16 in docker-compose.yml),
# installed by the Dockerfile
PG_DUMP = "/usr/lib/postgresql/16/bin/pg_dump"


def clear_expired_sessions():
    """Daily (see core/migrations/0001): Django never deletes expired sessions by
    itself. Same as `manage.py clearsessions` for the database backend. Returns
    the count, which django_q shows as the task's result in the admin."""
    deleted, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
    return deleted


def purge_old_task_results():
    """Daily (see core/migrations/0001): django_q keeps the last 250 successful
    tasks (save_limit) and every failed one, forever. Returns the count, which
    django_q shows as the task's result in the admin."""
    cutoff = timezone.now() - datetime.timedelta(days=TASK_HISTORY_DAYS)
    deleted, _ = Task.objects.filter(stopped__lt=cutoff).delete()
    return deleted


class BackupError(RuntimeError):
    pass


def backup_database():
    """Daily (see core/migrations/0002): dumps the database and uploads it to the
    BACKUP_S3_* bucket. Skipped when BACKUP_S3_BUCKET is unset, as on development
    machines. A failure emails the admins as well as failing the task. Returns the
    object key.

    The bucket keeps each dump for 30 days through its own expiry rule; the
    credentials here can only write to it, so a leaked .env can neither read nor
    delete the backups.

    To restore, with a dump downloaded by an admin (e.g. `mc cp`) into the
    project folder:

        docker compose stop web qcluster
        docker compose run --rm --no-deps -T web sh -c \\
          'PGPASSWORD="$POSTGRES_PASSWORD" /usr/lib/postgresql/16/bin/pg_restore \\
           --clean --if-exists --no-owner -h "$POSTGRES_HOST" -U "$POSTGRES_USER" \\
           -d "$POSTGRES_DB"' < energyguard-<date>.dump
        docker compose up -d

    Then re-delete the accounts deleted since the dump was taken (the completed
    deletion PrivacyRequests): the restore brings them back.
    """
    if not settings.BACKUP_S3_BUCKET:
        return "skipped: BACKUP_S3_BUCKET is not set"
    try:
        return _dump_and_upload()
    except Exception:
        logger.exception("Database backup failed")
        mail_admins("Database backup failed", traceback.format_exc(), fail_silently=True)
        raise


def _dump_and_upload():
    db = settings.DATABASES["default"]
    key = f"energyguard-{timezone.now():%Y-%m-%dT%H%M%SZ}.dump"
    with tempfile.TemporaryFile() as dump:
        result = subprocess.run(
            [PG_DUMP, "--format=custom", "--host", db["HOST"], "--port", str(db["PORT"]),
             "--username", db["USER"], "--dbname", db["NAME"]],
            stdout=dump,
            stderr=subprocess.PIPE,
            env={**os.environ, "PGPASSWORD": db["PASSWORD"]},
            timeout=15 * 60,
        )
        if result.returncode:
            raise BackupError(f"pg_dump exited with {result.returncode}: {result.stderr.decode(errors='replace')}")

        dump.seek(0)
        client = boto3.client(
            "s3",
            endpoint_url=settings.BACKUP_S3_ENDPOINT,
            aws_access_key_id=settings.BACKUP_S3_ACCESS_KEY,
            aws_secret_access_key=settings.BACKUP_S3_SECRET_KEY,
            config=Config(connect_timeout=10, read_timeout=60),
        )
        client.upload_fileobj(dump, settings.BACKUP_S3_BUCKET, key)
    return key
