"""Forms of the BER staff management panel."""

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS

from .services.results import BER_SIGNAL_INFO, has_power_signals

# Real .lp signal logs are ~500 MB. The cap is there to protect the server's
# disk (Django spools each upload to a temp file) rather than to be reached, and
# sits under the reverse proxy's client_max_body_size of 2000m so staff get this
# message instead of a bare HTTP 413 from the proxy.
RESULT_FILE_MAX_SIZE_BYTES = 1900 * 1024 * 1024
RESULT_FILE_MAX_SIZE_LABEL = '1.9 GB'
REJECTION_REASON_MAX_WORDS = 2000


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
        if result_file.size > RESULT_FILE_MAX_SIZE_BYTES:
            raise forms.ValidationError(f'Result file exceeds the {RESULT_FILE_MAX_SIZE_LABEL} limit.')
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
    pass


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
