from django.contrib.auth.decorators import login_required
from django.shortcuts import render

@login_required
def team_management(request):
    return render(request, 'accounts/team_management.html')