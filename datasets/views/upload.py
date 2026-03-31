import logging
import os
import shutil
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django_q.tasks import async_task

from core.views import BaseWizardView

from ..forms import FileUploadDatasetForm, GeneralDatasetForm, MetadataDatasetForm
from ..tasks import process_dataset_upload

logger = logging.getLogger(__name__)

DATASET_TEMPLATE_NAMES = {
    "general_info": "datasets/upload-dataset-step1.html",
    "upload_files": "datasets/upload-dataset-step2.html",
    "metadata": "datasets/upload-dataset-step3.html",
}
DATASET_FORMS = [
    ("general_info", GeneralDatasetForm),
    ("upload_files", FileUploadDatasetForm),
    ("metadata", MetadataDatasetForm),
]
DATASET_STEP_METADATA = {
    "general_info": {"title": "General", "icon": "fa-info-circle"},
    "upload_files": {"title": "Upload", "icon": "fa-upload"},
    "metadata": {"title": "Metadata", "icon": "fa-sheet-plastic"},
}

_TMP_UPLOAD_DIR = os.path.join(settings.BASE_DIR, "dataset_upload_tmp")


class AddDatasetView(LoginRequiredMixin, BaseWizardView):
    template_names = DATASET_TEMPLATE_NAMES
    step_metadata = DATASET_STEP_METADATA
    cancel_url = "/datasets/"

    def _cleanup_wizard_step_files(self) -> None:
        storage = getattr(self, "storage", None)
        if storage is None:
            return

        data = getattr(storage, "data", {})
        step_files_key = getattr(storage, "step_files_key", "step_files")
        wizard_files = data.get(step_files_key, {})

        for step_files in wizard_files.values():
            for step_file in step_files.values():
                tmp_name = step_file.get("tmp_name")
                if not tmp_name:
                    continue
                try:
                    self.file_storage.delete(tmp_name)
                except Exception:
                    logger.warning(
                        "Failed to cleanup wizard temp file '%s' in dataset upload flow.",
                        tmp_name,
                    )
                    continue

    def _save_to_tmp_dir(self, data_file, metadata_file) -> str:
        """Copies uploaded files to a persistent temp directory and returns its path."""
        tmp_dir = os.path.join(_TMP_UPLOAD_DIR, uuid.uuid4().hex)
        os.makedirs(tmp_dir, exist_ok=True)

        data_filename = data_file.name.split("/")[-1].split("\\")[-1]
        data_file.seek(0)
        with open(os.path.join(tmp_dir, data_filename), "wb") as f:
            shutil.copyfileobj(data_file, f)

        if metadata_file:
            metadata_filename = metadata_file.name.split("/")[-1].split("\\")[-1]
            metadata_file.seek(0)
            with open(os.path.join(tmp_dir, metadata_filename), "wb") as f:
                shutil.copyfileobj(metadata_file, f)

        return tmp_dir

    def done(self, form_list, **kwargs):
        try:
            general_data = self.get_cleaned_data_for_step("general_info")
            upload_data = self.get_cleaned_data_for_step("upload_files")
            metadata_data = self.get_cleaned_data_for_step("metadata")
            data_uploaded_file = upload_data["data_file"]
            metadata_uploaded_file = metadata_data.get("metadata_file")
            metadata_json = metadata_data.get("metadata")

            size_gb = (Decimal(data_uploaded_file.size) / Decimal(1024 ** 3)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if size_gb < Decimal("0.01"):
                size_gb = Decimal("0.01")

            try:
                tmp_dir = self._save_to_tmp_dir(data_uploaded_file, metadata_uploaded_file)
            except Exception:
                logger.exception(
                    "Failed to save uploaded files to temp dir for user '%s', dataset '%s'.",
                    self.request.user.username,
                    general_data.get("name", ""),
                )
                messages.error(
                    self.request,
                    "Failed to process uploaded files — please try again.",
                )
                return redirect("dataset_upload")

            data_filename = data_uploaded_file.name.split("/")[-1].split("\\")[-1]
            metadata_filename = (
                metadata_uploaded_file.name.split("/")[-1].split("\\")[-1]
                if metadata_uploaded_file
                else None
            )
            user = self.request.user

            async_task(
                process_dataset_upload,
                tmp_dir=tmp_dir,
                data_file_name=data_filename,
                data_file_content_type=data_uploaded_file.content_type or "application/octet-stream",
                metadata_file_name=metadata_filename,
                metadata_file_content_type=(
                    metadata_uploaded_file.content_type if metadata_uploaded_file else None
                ),
                metadata_json=metadata_json,
                dataset_name=general_data["name"],
                dataset_label=general_data["label"],
                dataset_visibility=general_data["visibility"],
                dataset_description=general_data["description"],
                size_gb=str(size_gb),
                user_id=user.pk,
                user_username=user.username or str(user.pk),
                user_email=user.email or "",
                user_display_name=user.get_full_name() or user.username,
                site_url=self.request.build_absolute_uri("/"),
            )

            self.request.session["dataset_upload_success"] = True
            return redirect("dataset-upload-success")
        finally:
            self._cleanup_wizard_step_files()


@login_required
def dataset_upload_success(request):
    if not request.session.pop("dataset_upload_success", False):
        return redirect("dataset_upload")
    wizard = {"steps": {"current": "done", "index": 0}}
    wizard_steps = DATASET_STEP_METADATA.values()
    return render(
        request,
        "datasets/upload-dataset-success.html",
        {"wizard": wizard, "wizard_steps": wizard_steps, "cancel_url": "/datasets/"},
    )
