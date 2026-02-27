import json

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
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
    metadata_rows = forms.CharField(required=False, widget=forms.HiddenInput())

    metadata_file = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['json'])],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = Dataset
        fields = ('metadata',)
        widgets = {
            'metadata': forms.HiddenInput(),
        }

    def clean(self):
        cleaned_data = super().clean()
        rows_raw = cleaned_data.get('metadata_rows')
        metadata_file = cleaned_data.get('metadata_file')
        metadata_value = cleaned_data.get('metadata')
        metadata_map = {}

        if rows_raw:
            try:
                rows_data = json.loads(rows_raw)
            except json.JSONDecodeError as exc:
                raise ValidationError("Invalid metadata rows payload.") from exc

            if not isinstance(rows_data, list):
                raise ValidationError("Metadata rows must be a list.")

            for row in rows_data:
                if not isinstance(row, dict):
                    raise ValidationError("Each metadata row must be an object.")

                feature_name = str(row.get('feature_name', '')).strip()
                feature_unit = str(row.get('feature_unit', '')).strip()
                feature_description = str(row.get('feature_description', '')).strip()

                # Ignore fully empty rows.
                if not any([feature_name, feature_unit, feature_description]):
                    continue

                if not feature_name:
                    raise ValidationError("Feature name is required for each metadata row.")

                if feature_name in metadata_map:
                    raise ValidationError(f"Duplicate feature name: '{feature_name}'.")

                metadata_map[feature_name] = [feature_unit, feature_description]

        if metadata_file and metadata_map:
            raise ValidationError(
                "Choose one metadata input method: upload a metadata file or add rows manually."
            )

        if not metadata_file and not metadata_map:
            raise ValidationError(
                "Provide metadata either by uploading a metadata file or by adding rows manually."
            )

        if metadata_map:
            cleaned_data['metadata'] = metadata_map
        elif not metadata_value:
            cleaned_data['metadata'] = None

        return cleaned_data

class FileUploadDatasetForm(forms.Form):
    data_file = forms.FileField(
        validators=[FileExtensionValidator(allowed_extensions=['zip', 'csv'])],
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
    )

    def clean_data_file(self):
        uploaded = self.cleaned_data.get('data_file')
        if not uploaded:
            return uploaded
        filename = (uploaded.name or "").lower()
        extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        content_type = (uploaded.content_type or "").lower()

        # Browsers/OSes often report CSV as application/vnd.ms-excel or text/plain.
        allowed_types_by_extension = {
            "zip": {
                "application/zip",
                "application/x-zip-compressed",
                "multipart/x-zip",
                "application/octet-stream",
            },
            "csv": {
                "text/csv",
                "application/csv",
                "application/vnd.ms-excel",
                "text/plain",
                "application/octet-stream",
            },
        }

        allowed_types = allowed_types_by_extension.get(extension, set())
        if content_type and content_type not in allowed_types:
            raise ValidationError("Only .zip or .csv files are allowed.")
        return uploaded
