from django import forms

from .models import Project

class ProjectGeneralInfoForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'description', 'project_type')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter project name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter project description', 'rows': 3}),
            'project_type': forms.Select(attrs={'class': 'form-select'}),
        }
        # The same text as the browser-side message, for a form that reaches the server
        error_messages = {
            'name': {'required': 'Please enter a project name.'},
            'project_type': {'required': 'Please choose a project type.'},
        }

class EditProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ('name', 'description', 'project_type')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter project name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter project description', 'rows': 3}),
            'project_type': forms.Select(attrs={'class': 'form-select'}),
        }

class ExperimentGeneralInfoForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter experiment name"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-control", "placeholder": "Enter experiment description", "rows": 3}
        ),
    )


class ExperimentEditForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter experiment name"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-control", "placeholder": "Enter experiment description", "rows": 3}
        ),
    )


class ExperimentFacilitiesForm(forms.Form):
    facility_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter facility name"}),
    )


class ExperimentSandboxPackagesForm(forms.Form):
    package_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter sandbox package name"}),
    )
