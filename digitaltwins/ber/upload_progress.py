"""Server-side progress of a result-file upload to MinIO.

The management panel uploads by XHR, so the browser knows when its own bytes
are sent; this publishes the second half (the copy to MinIO) for it to poll.
"""

import re
import threading
import time

from django.core.cache import cache

UPLOAD_ID_RE = re.compile(r'^[A-Za-z0-9-]{8,64}$')
_PROGRESS_TIMEOUT = 3600
_WRITE_INTERVAL = 0.5  # seconds; boto3 calls back per chunk, far too often to write each


def progress_key(user_id, upload_id):
    # Scoped by user so one staff member can't read another's upload by guessing ids.
    return f'ber_upload_progress_{user_id}_{upload_id}'


def read_progress(user_id, upload_id):
    return cache.get(progress_key(user_id, upload_id))


class UploadProgress:
    """boto3 upload Callback that publishes how much of the result file has reached
    MinIO, so the panel's progress bar can keep counting after the browser upload.
    Called from several threads during multipart uploads, hence the lock."""

    def __init__(self, cache_key, total):
        self.cache_key = cache_key
        self.total = total
        self.sent = 0
        self._lock = threading.Lock()
        self._last_write = 0.0
        cache.set(cache_key, {'sent': 0, 'total': total}, timeout=_PROGRESS_TIMEOUT)

    def __call__(self, bytes_amount):
        with self._lock:
            self.sent += bytes_amount
            now = time.monotonic()
            if self.sent < self.total and now - self._last_write < _WRITE_INTERVAL:
                return
            self._last_write = now
            cache.set(
                self.cache_key, {'sent': min(self.sent, self.total), 'total': self.total},
                timeout=_PROGRESS_TIMEOUT,
            )


def progress_callback_for(request, result_file):
    """Progress tracker for this upload, or None if the form sent no (valid) upload id."""
    upload_id = request.POST.get('upload_id', '')
    if not UPLOAD_ID_RE.match(upload_id):
        return None
    return UploadProgress(progress_key(request.user.pk, upload_id), result_file.size)
