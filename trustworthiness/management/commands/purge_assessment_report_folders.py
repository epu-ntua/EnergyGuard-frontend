"""
Delete the report folders code analysis and robustness used to write to disk
(analysis_reports/<job>/ and robustness_reports/<job>/, each a final_report.json
and a meta.json). The Assessment rows hold the same results and are now the only
source; the folders were never deleted, not even with their Assessment or its
owner's account.

    python manage.py purge_assessment_report_folders           # report only
    python manage.py purge_assessment_report_folders --apply   # delete

A folder whose Assessment has no results first copies them into it; one whose
report can't be read then is kept, and listed. Folders linked to no Assessment,
from runs before every run needed a project or of deleted ones, are deleted
unread.
"""

import json
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand

from trustworthiness.models import Assessment

REPORT_DIRS = {
    "analysis_reports": Assessment.AssessmentType.CODE_ANALYSIS,
    "robustness_reports": Assessment.AssessmentType.ROBUSTNESS,
}

# The meta.json keys the Assessment keeps in input_data since the folders went
META_KEYS = ("job_id", "backend_job_id")


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Command(BaseCommand):
    help = "Delete the old assessment report folders, after checking their results are in the database."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Delete (default: only report what would happen).")

    def handle(self, *args, apply, **options):
        counts = {"in the database": 0, "copied to the database": 0, "no assessment": 0, "kept, unreadable": 0}
        for dir_name, assessment_type in REPORT_DIRS.items():
            root = settings.BASE_DIR / dir_name
            if not root.is_dir():
                continue
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                outcome = self._handle_folder(folder, assessment_type, apply)
                counts[outcome] += 1
                self.stdout.write(f"{dir_name}/{folder.name}: {outcome}")
            if apply and not any(root.iterdir()):
                root.rmdir()

        self.stdout.write(", ".join(f"{count} {outcome}" for outcome, count in counts.items()))
        if not apply:
            self.stdout.write("Nothing changed. Run with --apply to delete.")

    def _handle_folder(self, folder, assessment_type, apply):
        meta = _read_json(folder / "meta.json") or {}
        assessment = Assessment.objects.filter(
            id=meta.get("assessment_id") or None, assessment_type=assessment_type,
        ).first()

        if assessment is None:
            outcome = "no assessment"
        elif assessment.results:
            outcome = "in the database"
        else:
            report = _read_json(folder / "final_report.json")
            if not report:
                return "kept, unreadable"
            outcome = "copied to the database"
            if apply:
                assessment.results = report
                assessment.status = Assessment.Status.COMPLETED
                assessment.save(update_fields=["results", "status"])

        if assessment is not None and apply:
            missing = {key: meta[key] for key in META_KEYS if meta.get(key) and key not in (assessment.input_data or {})}
            if missing:
                assessment.input_data = {**(assessment.input_data or {}), **missing}
                assessment.save(update_fields=["input_data"])

        if apply:
            shutil.rmtree(folder)
        return outcome
