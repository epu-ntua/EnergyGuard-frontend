from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def hpc(request):
    return render(request, 'core/hpc.html', {
        'show_sidebar': True,
        'active_navbar_page': 'hpc',
    })
