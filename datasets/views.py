from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django_datatables_view.base_datatable_view import BaseDatatableView
from .models import Dataset, DatasetUserDownload
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F


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