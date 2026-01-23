from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from .models import Dataset, DatasetUserDownload
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F
from .forms import GeneralDatasetForm, FileUploadDatasetForm, MetadataDatasetForm
from core.views import BaseWizardView
from django.db import transaction
from django_datatables_view.base_datatable_view import BaseDatatableView


class DatasetsListJson(BaseDatatableView):
    model = Dataset
    columns = [
        "name",
        # "users",
        "created_at",
        "label",
        "source",
        "publisher",
        "size_gb",
        "downloads",
        "status",
        "id",
    ]
    order_columns = [
        "name",
        # "users",
        "created_at",
        "label",
        "source",
        "publisher",
        "size_gb",
        "downloads",
        "status",
    ]
    max_display_length = 25

    def get_initial_queryset(self):
        # Prefetch related users to optimize DB queries
        return Dataset.objects.prefetch_related("users").all()

    def filter_queryset(self, qs):
        # Handle search and status filtering
        search = self.request.GET.get("search[value]")
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(label__icontains=search)
                | Q(source__icontains=search)
                | Q(status__icontains=search)
                # | Q(users__username__icontains=search)
            ).distinct()

        status_filter = self.request.GET.get("status")
        if status_filter in ["published", "private", "restricted", "under_review"]:
            qs = qs.filter(status=status_filter)

        return qs

    def render_column(self, row, column):
        # # Render specific columns with custom HTML or formatting
        # if column == "users":
        #     return ", ".join(user.username for user in row.users.all()) or "No collaborators"
        if column == "created_at":
            return row.created_at.strftime("%b %d, %Y")
        elif column == "label":
            return row.get_label_display()
        elif column == "source":
            return row.get_source_display()
        elif column == "size_gb":
            return row.size_gb
        elif column == "status":
            status = row.status.replace("_", " ").title()
            map = {
                "published": "badge-phoenix-success",
                "under_review": "badge-phoenix-primary",
                "private": "badge-phoenix-danger",
                "restricted": "badge-phoenix-warning",
            }
            badge_class = map.get(row.status, "badge-phoenix-secondary")
            return f'<div class="text-end"><span class="badge badge-phoenix {badge_class} fs-11"><span class="badge-label">{status}</span></span></div>'
        else:
            return super().render_column(row, column)
        
@login_required
def datasets_list(request):
    # Prepare context for initial page load (dataset counts, etc.)
    qs = Dataset.objects.all()
    counts = {
        "all": qs.count(),
        "published": qs.filter(status="published").count(),
        "private": qs.filter(status="private").count(),
        "restricted": qs.filter(status="restricted").count(),
        "under_review": qs.filter(status="under_review").count(),
    }
    status_filter = request.GET.get("status")

    return render(
        request,
        "datasets/datasets-list.html",
        {
            "dataset_num": counts,
            "status_filter": status_filter,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )

@login_required
def dataset_details(request, dataset_id):
    # Fetch and display details for a single dataset
    try:
        dataset = Dataset.objects.prefetch_related("users").get(pk=dataset_id)
    except Dataset.DoesNotExist:
        messages.error(request, "Dataset not found")
        return redirect("home")

    dataset_details = {
        "id": dataset.id,
        "name": dataset.name,
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
        "status": dataset.status,
        "label": dataset.get_label_display(),
        "source": dataset.get_source_display(),
        "visibility": dataset.visibility,
        "size": dataset.size_gb,
        "publisher": dataset.publisher,
        "description": dataset.description,
        "metadata": dataset.metadata,
        "collaborators": ", ".join(user.username for user in dataset.users.all()),
        # "downloaded": request.user in dataset.users_downloads,
        "downloaded": DatasetUserDownload.objects.filter(user=request.user, dataset=dataset).exists(),
    }

    return render(
        request,
        "datasets/dataset-details.html",
        {
            "dataset": dataset,
            "dt": dataset_details,
            "active_navbar_page": "datasets",
            "show_sidebar": True,
        },
    )

@login_required
def dataset_download(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if request.user.credits < 100:
        messages.error(request, "Insufficient credits to download the dataset.")
        return redirect('dataset_details', dataset_id=dataset.id)
    
    # F() increment to avoid race conditions
    Dataset.objects.filter(pk=dataset.id).update(downloads=F('downloads') + 1)
    DatasetUserDownload.objects.create(user=request.user, dataset=dataset)

    request.user.credits = F('credits') - 100
    request.user.save()

    messages.success(request, f"You have successfully downloaded the dataset: {dataset.name}")
    return redirect('dataset_details', dataset_id=dataset.id)

DATASET_TEMPLATE_NAMES = {
    'general_info': "datasets/add-dataset-step1.html",
    'upload_files': "datasets/add-dataset-step2.html",
    'metadata': "datasets/add-dataset-step3.html",
}
DATASET_FORMS = [
    ('general_info', GeneralDatasetForm),
    ('upload_files', FileUploadDatasetForm),
    ('metadata', MetadataDatasetForm),
]
DATASET_STEP_METADATA = {
    'general_info': {'title': 'General', 'icon': 'fa-info'},
    'upload_files': {'title': 'Upload', 'icon': 'fa-upload'},
    'metadata': {'title': 'Metadata', 'icon': 'fa-info-circle'},
}

class AddDatasetView(LoginRequiredMixin, BaseWizardView):
    template_names = DATASET_TEMPLATE_NAMES
    step_metadata = DATASET_STEP_METADATA

    def done(self, form_list, **kwargs):
        # Process and save dataset after all steps are completed

        general_data = self.get_cleaned_data_for_step('general_info') 
        upload_data = self.get_cleaned_data_for_step('upload_files') 
        metadata_data = self.get_cleaned_data_for_step('metadata') 

        with transaction.atomic():
            dataset = Dataset.objects.create(
                name=general_data['name'],
                data_file=upload_data['data_file'],
                label=general_data['label'],
                source='your_own_DS',
                status='under_review',
                visibility=general_data['visibility'],
                size_gb=upload_data['data_file'].size / (1024 * 1024 * 1024),
                publisher=self.request.user.username,
                description=general_data['description'],
                metadata=metadata_data['metadata'],
            )

        return redirect('dataset-upload-success')

