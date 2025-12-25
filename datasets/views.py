from django.shortcuts import render, redirect
from django.db.models import Q
from .models import Dataset
from django.http import JsonResponse

# Create your views here.
"""def datasets_list(request):

    data = Dataset.objects.all()

    # Number of all/published/private/restricted/under_review datasets
    counts = {
        "all": data.count(),
        "published": data.filter(status="published").count(),
        "private": data.filter(status="private").count(),
        "restricted": data.filter(status="restricted").count(),
        "under_review": data.filter(status="under_review").count(),
    }
    
    # Sort data according to column
    sort = request.GET.get('sort') 
    if sort in ['name', 'created_at', 'updated', 'label', 'source']:
        data = data.order_by(sort)

    # Filter data according to status
    status_filter = request.GET.get("status")
    if status_filter in ["published", "private", "restricted", "under_review"]:
        data = data.filter(status=status_filter)

    # Pagination implementation for 8 datasets per page
    p = Paginator(data, 7)
    page_number = request.GET.get("page")
    filtered_data = p.get_page(page_number)

    return render(request, 'mysite/dataset-list.html', {"dataset" : filtered_data, "dataset_num": counts, "status_filter": status_filter, "active_navbar_page": "datasets", "show_vertical_navbar": True})"""

def datasets_list(request):
    # DataTables AJAX branch
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.GET.get("draw"):
        draw = int(request.GET.get("draw", 1))
        start = int(request.GET.get("start", 0))
        length = int(request.GET.get("length", 10))
        search_value = request.GET.get("search[value]", "")
        status_filter = request.GET.get("status")

        order_col = request.GET.get("order[0][column]", "3")
        order_dir = request.GET.get("order[0][dir]", "desc")
        column_map = {
            "1": "name",
            "2": "users__first_name",
            "3": "created_at",
            "4": "updated_at",
            "5": "label",
            "6": "source",
            "7": "status",
        }
        ordering = column_map.get(order_col, "created_at")
        if order_dir == "desc":
            ordering = f"-{ordering}"

        qs = Dataset.objects.prefetch_related("users").all()
        if status_filter in ["published", "private", "restricted", "under_review"]:
            qs = qs.filter(status=status_filter)

        records_total = qs.count()

        if search_value:
            qs = qs.filter(
                Q(name__icontains=search_value)
                | Q(label__icontains=search_value)
                | Q(source__icontains=search_value)
                | Q(status__icontains=search_value)
                | Q(users__username__icontains=search_value)
            ).distinct()

        records_filtered = qs.count()
        qs = qs.order_by(ordering)[start:start + length]

        data = []
        for d in qs:
            collaborators = ", ".join(d.users.values_list("username", flat=True)) or "No collaborators"
            data.append({
                "id": d.id,
                "name": d.name,
                "users": collaborators,
                "created_at": d.created_at.strftime("%b %d, %Y"),
                "updated_at": d.updated_at.strftime("%b %d, %Y"),
                "label": d.get_label_display(),
                "source": d.get_source_display(),
                "visibility": d.visibility,
                "size_gb": f'{d.size_gb} GB',
                "downloads": d.downloads,
                "publisher": d.publisher,
                "status": d.status,
                "status_badge": d.status,
            })

        return JsonResponse({
            "draw": draw,
            "recordsTotal": records_total,
            "recordsFiltered": records_filtered,
            "data": data,
        })

    # Initial page render (no paginator)
    data = Dataset.objects.all()
    counts = {
        "all": data.count(),
        "published": data.filter(status="published").count(),
        "private": data.filter(status="private").count(),
        "restricted": data.filter(status="restricted").count(),
        "under_review": data.filter(status="under_review").count(),
    }
    status_filter = request.GET.get("status")
    return render(request, "mysite/datasets-list.html", {
        "dataset_num": counts,
        "status_filter": status_filter,
        "active_navbar_page": "datasets",
        "show_vertical_navbar": True,
    })

def dataset_details(request, dataset_id):

    dataset = Dataset.objects.filter(pk=dataset_id).first()  # avoid exception if not found

    if dataset:
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
            "metadata": dataset.metadata
        }
    else:
        return redirect('error_does_not_exist', error= "Dataset not found")

    return render(request, 'mysite/dataset-details.html', {"dataset": dataset, "dt": dataset_details, "active_navbar_page": "datasets", "show_vertical_navbar": True})
