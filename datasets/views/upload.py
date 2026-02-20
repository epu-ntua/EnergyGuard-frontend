from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render

from core.views import BaseWizardView

from ..forms import FileUploadDatasetForm, GeneralDatasetForm, MetadataDatasetForm
from ..models import Dataset
from ..services import MinioUploadError, upload_dataset_objects

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


class AddDatasetView(LoginRequiredMixin, BaseWizardView):
    template_names = DATASET_TEMPLATE_NAMES
    step_metadata = DATASET_STEP_METADATA

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
                    continue

    def done(self, form_list, **kwargs):
        try:
            general_data = self.get_cleaned_data_for_step("general_info")
            upload_data = self.get_cleaned_data_for_step("upload_files")
            metadata_data = self.get_cleaned_data_for_step("metadata")
            data_uploaded_file = upload_data["data_file"]
            metadata_uploaded_file = metadata_data.get("metadata_file")
            metadata_json = metadata_data.get("metadata")

            try:
                upload_result = upload_dataset_objects(
                    user_name=self.request.user.username or str(self.request.user.pk),
                    dataset_name=general_data["name"],
                    data_file=data_uploaded_file,
                    metadata_file=metadata_uploaded_file,
                    metadata_json=metadata_json,
                )
            except MinioUploadError as exc:
                messages.error(self.request, f"Failed to upload dataset to MinIO: {exc}")
                return redirect("dataset_upload")

            size_gb = (Decimal(data_uploaded_file.size) / Decimal(1024 ** 3)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if size_gb < Decimal("0.01"):
                size_gb = Decimal("0.01")

            with transaction.atomic():
                Dataset.objects.create(
                    name=general_data["name"],
                    data_file=upload_result["data_file_key"],
                    metadata_file=upload_result["metadata_file_key"],
                    bucket_name=upload_result["bucket_name"],
                    label=general_data["label"],
                    source="your_own_DS",
                    status="under_review",
                    visibility=general_data["visibility"],
                    size_gb=size_gb,
                    publisher=self.request.user,
                    description=general_data["description"],
                    metadata=metadata_json,
                )

            return redirect("dataset-upload-success")
        finally:
            self._cleanup_wizard_step_files()


@login_required
def dataset_upload_success(request):
    wizard = {"steps": {"current": "done"}}
    wizard_steps = DATASET_STEP_METADATA.values()
    return render(
        request,
        "datasets/upload-dataset-success.html",
        {"wizard": wizard, "wizard_steps": wizard_steps},
    )
