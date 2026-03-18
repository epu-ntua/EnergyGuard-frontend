from django.contrib import admin
from .models import Experiment, Project, ProjectCollaborator

# Register your models here.
admin.site.register(Project)
admin.site.register(ProjectCollaborator)
admin.site.register(Experiment)
