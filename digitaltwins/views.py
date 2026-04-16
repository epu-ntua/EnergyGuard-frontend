from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def map_view(request):
    return render(request, 'digitaltwins/map.html', {'show_sidebar': True})
