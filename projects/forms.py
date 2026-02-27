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

class ProjectFacilitiesForm(forms.Form):
    facility_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter facility name'}),
    )

class ProjectSandboxPackagesForm(forms.Form): 
    package_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter sandbox package name'}),
    )


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
    tags = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Comma-separated tags (e.g. baseline,forecast,v1)",
            }
        ),
        help_text="Comma-separated tags.",
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
