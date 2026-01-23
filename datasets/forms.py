from django import forms
from datasets.models import Dataset

class GeneralDatasetForm(forms.ModelForm):
    class Meta:
        model = Dataset
        fields = ('name', 'description', 'label', 'visibility')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter dataset name'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter dataset description', 'rows': 2}),
            'label': forms.Select(attrs={'class': 'form-select'}),
            'visibility': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [('', 'Select Label')] + list(self.fields['label'].choices)
        self.fields['label'].choices = choices
        self.fields['label'].initial = ''

class MetadataDatasetForm(forms.ModelForm):
    class Meta:
        model = Dataset
        fields = ('metadata',)
        widgets = {
            'metadata': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Enter dataset metadata in JSON format', 'rows': 5}),
        }

class FileUploadDatasetForm(forms.ModelForm):
    class Meta:
        model = Dataset
        fields = ('data_file',)
        widgets = {
            'data_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
