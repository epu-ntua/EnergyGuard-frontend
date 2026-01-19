from django.shortcuts import render

# Create your views here.
def assets_list(request):
    return render(request, 'assets/assets-list.html', {})