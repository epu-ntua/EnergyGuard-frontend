from django import forms
from experiments.models import Experiment

class ExperimentGeneralInfoForm(forms.ModelForm):
    class Meta:
        model = Experiment
        fields = ('name', 'description', 'exp_type')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter project name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter project description', 'rows': 3}),
            'exp_type': forms.Select(attrs={'class': 'form-select'}),
        }

class ExperimentFacilitiesForm(forms.Form):
    facility_name = forms.CharField( max_length=255, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter facility name'}) )

class ExperimentSandboxPackagesForm(forms.Form): 
    package_name = forms.CharField( max_length=255, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter sandbox package name'}) )