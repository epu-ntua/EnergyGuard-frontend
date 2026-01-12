from django.contrib import admin
from .models import Experiment, ExperimentCollaborator

# Register your models here.
admin.site.register(Experiment)
admin.site.register(ExperimentCollaborator)