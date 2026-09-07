from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):
    return render(request, 'dataspace/index.html', {
        'show_sidebar': True,
        'active_navbar_page': 'dataspace',
        'dataspace_gateway_url': settings.DATASPACE_GATEWAY_URL,
    })
