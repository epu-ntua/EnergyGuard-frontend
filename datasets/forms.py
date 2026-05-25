import json

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from datasets.models import Dataset

_MAX_DATA_FILE_SIZE_MB = 500
_MAX_METADATA_FILE_SIZE_MB = 10

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


class FileUploadPlaceholderForm(forms.Form):
    """
    Step 2 form — no file field. The browser uploads directly to MinIO via a
    presigned URL; we only store the resulting object key and metadata here.
    """
    upload_key = forms.CharField(widget=forms.HiddenInput())
    bucket_name = forms.CharField(widget=forms.HiddenInput())
    file_size_bytes = forms.IntegerField(widget=forms.HiddenInput(), min_value=1)
    original_filename = forms.CharField(widget=forms.HiddenInput())
    content_type = forms.CharField(widget=forms.HiddenInput())

    def clean_upload_key(self):
        key = self.cleaned_data.get("upload_key", "").strip()
        if not key:
            raise ValidationError("No file upload was initiated. Please select a file.")
        return key

    def clean_file_size_bytes(self):
        size = self.cleaned_data.get("file_size_bytes")
        if not size or size <= 0:
            raise ValidationError("Invalid file size.")
        max_bytes = _MAX_DATA_FILE_SIZE_MB * 1024 * 1024
        if size > max_bytes:
            raise ValidationError(f"File size must not exceed {_MAX_DATA_FILE_SIZE_MB} MB.")
        return size


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

    def clean_metadata_file(self):
        metadata_file = self.cleaned_data.get('metadata_file')
        if not metadata_file:
            return metadata_file

        max_bytes = _MAX_METADATA_FILE_SIZE_MB * 1024 * 1024
        if metadata_file.size > max_bytes:
            raise ValidationError(f"Metadata file size must not exceed {_MAX_METADATA_FILE_SIZE_MB} MB.")

        try:
            metadata_file.seek(0)
            content = metadata_file.read()
            parsed = json.loads(content)
            metadata_file.seek(0)
        except json.JSONDecodeError:
            raise ValidationError("Metadata file must contain valid JSON.")
        except Exception:
            raise ValidationError("Could not read the metadata file.")

        if not isinstance(parsed, dict):
            raise ValidationError(
                "Metadata file must be a JSON object (e.g. {\"feature\": [\"unit\", \"description\"]})."
            )
        for feature_name, value in parsed.items():
            if not isinstance(feature_name, str) or not feature_name.strip():
                raise ValidationError("Each key in the metadata file must be a non-empty string (feature name).")
            if not isinstance(value, list) or len(value) != 2:
                raise ValidationError(
                    'Invalid metadata file. Each feature must follow this format: '
                    '{"feature_name": ["unit", "description"]}'
                )

        return metadata_file

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

        if not metadata_file and not metadata_map and 'metadata_file' not in self.errors:
            raise ValidationError(
                "Provide metadata either by uploading a metadata file or by adding rows manually."
            )

        if metadata_map:
            cleaned_data['metadata'] = metadata_map
        elif metadata_file:
            metadata_file.seek(0)
            cleaned_data['metadata'] = json.loads(metadata_file.read())
        elif not metadata_value:
            cleaned_data['metadata'] = None

        return cleaned_data