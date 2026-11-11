"""
Fail the code analysis and robustness jobs a restart interrupted.

Their threads die with the web process, and without this their Assessments
would read 'running' until reconcile_stale_assessments, hours later. The web
container runs it on every start, before the server (see docker-compose.yml):
never run it while the web server is up, since it would fail live jobs too.

    python manage.py fail_interrupted_assessments
"""

from django.core.management.base import BaseCommand

from trustworthiness.jobs import fail_interrupted_jobs


class Command(BaseCommand):
    help = "Fail the assessment jobs left 'running' by a restart. Run only while the web server is down."

    def handle(self, *args, **options):
        self.stdout.write(f"{fail_interrupted_jobs()} interrupted assessment job(s) failed")
