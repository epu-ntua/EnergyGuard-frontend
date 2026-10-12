"""Forms of the BER staff management panel."""

from datetime import datetime, timezone

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS

from .services.results import BER_SIGNAL_INFO, has_power_signals

RESULT_FILE_MAX_SIZE_MB = 50  # real .lp signal logs, not the JSON request itself
REJECTION_REASON_MAX_WORDS = 2000

_INVALID_TIMES = 'Provide a valid start and end time.'


def first_error(form):
    """The first error in field order: the panel shows one message at a time."""
    for name in [*form.fields, NON_FIELD_ERRORS]:
        errors = form.errors.get(name)
        if errors:
            return errors[0]
    return None


class _ResultFileForm(forms.Form):
    # allow_empty_file: an empty upload gets the same "no power signals" message
    # as any other file the results page couldn't show.
    result_file = forms.FileField(
        allow_empty_file=True, error_messages={'required': 'Choose a result file to upload.'},
    )

    def clean_result_file(self):
        result_file = self.cleaned_data['result_file']
        if result_file.size > RESULT_FILE_MAX_SIZE_MB * 1024 * 1024:
            raise forms.ValidationError(f'Result file exceeds the {RESULT_FILE_MAX_SIZE_MB} MB limit.')
        # Checked before anything is stored or the requester is told their results
        # are ready: a file the results page can't chart would only reach them as
        # an error.
        readable = has_power_signals(result_file)
        result_file.seek(0)
        if not readable:
            raise forms.ValidationError(
                'This file has no power signals the results page can show '
                f'({", ".join(BER_SIGNAL_INFO)}). Upload the .lp result file of this experiment.'
            )
        return result_file


class CompleteRequestForm(_ResultFileForm):
    # Text, not DateTimeField: the panel's datetime-local inputs are labelled UTC
    # and must be read as UTC whatever the server's TIME_ZONE.
    # required=False so a missing value gets the same message as an invalid one.
    actual_start = forms.CharField(required=False)
    actual_end = forms.CharField(required=False)

    field_order = ['actual_start', 'actual_end', 'result_file']

    @staticmethod
    def _parse_utc(raw):
        try:
            return datetime.strptime(raw, '%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            raise forms.ValidationError(_INVALID_TIMES)

    def clean_actual_start(self):
        return self._parse_utc(self.cleaned_data['actual_start'])

    def clean_actual_end(self):
        return self._parse_utc(self.cleaned_data['actual_end'])

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('actual_start'), cleaned.get('actual_end')
        if start and end and end <= start:
            self.add_error('actual_end', 'End time must be after start time.')
        return cleaned


class RejectRequestForm(forms.Form):
    rejection_reason = forms.CharField(error_messages={'required': 'A rejection reason is required.'})

    def clean_rejection_reason(self):
        reason = self.cleaned_data['rejection_reason']
        word_count = len(reason.split())
        if word_count > REJECTION_REASON_MAX_WORDS:
            raise forms.ValidationError(
                f'The rejection reason can be at most {REJECTION_REASON_MAX_WORDS} words (it has {word_count}).'
            )
        return reason


class ReplaceResultForm(_ResultFileForm):
    pass
