import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from core.views import BaseWizardView

from ..forms import FileUploadPlaceholderForm, GeneralDatasetForm, MetadataDatasetForm
from ..services import MinioUploadError, generate_presigned_upload_url
from ..tasks import finalize_dataset_upload

logger = logging.getLogger(__name__)

DATASET_TEMPLATE_NAMES = {
    "general_info": "datasets/upload-dataset-step1.html",
    "upload_files": "datasets/upload-dataset-step2.html",
    "metadata": "datasets/upload-dataset-step3.html",
}
DATASET_FORMS = [
    ("general_info", GeneralDatasetForm),
    ("upload_files", FileUploadPlaceholderForm),
    ("metadata", MetadataDatasetForm),
]
DATASET_STEP_METADATA = {
    "general_info": {"title": "General", "icon": "fa-info-circle"},
    "upload_files": {"title": "Upload", "icon": "fa-upload"},
    "metadata": {"title": "Metadata", "icon": "fa-sheet-plastic"},
}

_FRAGMENT_TEMPLATE_NAMES = {
    "metadata": "datasets/upload-dataset-step3-fragment.html",
}


class AddDatasetView(LoginRequiredMixin, BaseWizardView):
    template_names = DATASET_TEMPLATE_NAMES
    step_metadata = DATASET_STEP_METADATA
    cancel_url = "/datasets/"

    def get_template_names(self):
        if self.request.headers.get("X-Wizard-Ajax") == "1":
            fragment = _FRAGMENT_TEMPLATE_NAMES.get(self.steps.current)
            if fragment:
                return [fragment]
        return super().get_template_names()

    def post(self, *args, **kwargs):
        is_ajax = self.request.headers.get("X-Wizard-Ajax") == "1"
        response = super().post(*args, **kwargs)
        if not is_ajax:
            return response
        if isinstance(response, HttpResponseRedirect):
            return JsonResponse({"redirect": response["Location"]})
        if hasattr(response, "render"):
            response.render()
        return JsonResponse({"html": response.content.decode("utf-8")})

    def done(self, form_list, **kwargs):
        upload_data = self.get_cleaned_data_for_step("upload_files")
        general_data = self.get_cleaned_data_for_step("general_info")
        metadata_data = self.get_cleaned_data_for_step("metadata")

        object_key = upload_data["upload_key"]
        bucket = upload_data["bucket_name"]
        file_size_bytes = upload_data["file_size_bytes"]

        size_gb = (Decimal(file_size_bytes) / Decimal(1024 ** 3)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if size_gb < Decimal("0.01"):
            size_gb = Decimal("0.01")

        user = self.request.user

        async_task(
            finalize_dataset_upload,
            object_key=object_key,
            bucket_name=bucket,
            user_id=user.pk,
            user_email=user.email or "",
            user_display_name=user.get_full_name() or user.username,
            dataset_name=general_data["name"],
            dataset_label=general_data["label"],
            dataset_visibility=general_data["visibility"],
            dataset_description=general_data["description"],
            dataset_size_gb=size_gb,
            dataset_metadata=metadata_data.get("metadata"),
            site_url=self.request.build_absolute_uri("/"),
        )

        if self.request.headers.get("X-Wizard-Ajax") == "1":
            return render(self.request, "datasets/upload-dataset-success-fragment.html", {
                "wizard_steps": DATASET_STEP_METADATA.values(),
            })

        self.request.session["dataset_upload_success"] = True
        return redirect("dataset-upload-success")


@login_required
@require_POST
def generate_upload_url(request):
    filename = request.POST.get("filename", "").strip()
    content_type = request.POST.get("content_type", "application/octet-stream")

    if not filename:
        return JsonResponse({"error": "Filename is required."}, status=400)

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ("csv", "zip"):
        return JsonResponse({"error": "Only .csv or .zip files are allowed."}, status=400)

    user_slug = slugify(request.user.username or str(request.user.pk)) or "user"
    safe_stem = slugify(filename.rsplit(".", 1)[0]) or "data"
    object_key = f"pending/{user_slug}/{uuid.uuid4().hex}/{safe_stem}.{ext}"

    try:
        url, bucket = generate_presigned_upload_url(
            object_key=object_key,
            content_type=content_type,
        )
    except MinioUploadError:
        logger.exception("Failed to generate presigned URL for user '%s'.", request.user.username)
        return JsonResponse({"error": "Could not prepare upload. Please try again."}, status=500)

    return JsonResponse({"url": url, "key": object_key, "bucket": bucket})


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
