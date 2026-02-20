from django.contrib import admin
from .models import Project, ProjectCollaborator

# Register your models here.
admin.site.register(Project)
admin.site.register(ProjectCollaborator)
