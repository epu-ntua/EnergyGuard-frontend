from django import forms

from .models import Experiment, Project

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


class ExperimentGeneralInfoForm(forms.ModelForm):
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

    class Meta:
        model = Experiment
        fields = ("name", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter experiment name"}),
            "description": forms.Textarea(
                attrs={"class": "form-control", "placeholder": "Enter experiment description", "rows": 3}
            ),
        }

    def clean_name(self):
        name = self.cleaned_data["name"]
        if Experiment.objects.filter(name=name).exists():
            raise forms.ValidationError(f'Experiment "{name}" already exists.')
        return name


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
