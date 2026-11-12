"""Reading ZIP datasets straight from MinIO, and the rule for what they may contain.

A dataset ZIP must hold CSV files only (folders are fine), and at least one.
The same rule is enforced in the browser before the upload starts
(upload-dataset-step2.html); this is the server-side check, since the browser
one can be bypassed.
"""

import logging
import posixpath
import zipfile

from core.services.object_storage import build_minio_client

logger = logging.getLogger(__name__)

# Why a ZIP was refused - the keys match FAILURE_REASONS in datasets/tasks.py.
ZIP_NO_CSV = "zip_no_csv"
ZIP_NON_CSV = "zip_non_csv"
ZIP_INVALID = "zip_invalid"
CSV_IS_ZIP = "csv_is_zip"

# Local file header, empty archive, spanned archive. Checked as whole 4-byte
# signatures, not just "PK", so a CSV whose header starts with "PK" is not mistaken.
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def is_zip_signature(magic: bytes) -> bool:
    return magic[:4] in _ZIP_SIGNATURES


class S3SeekableStream:
    """
    Wraps an S3/MinIO object as a seekable stream using Range requests.
    Allows zipfile.ZipFile to read only the bytes it needs (EOCD + central
    directory + the specific entry) instead of downloading the full file.
    Uses a 512 KB read-ahead buffer to minimise the number of HTTP requests.
    """

    _BUFFER_SIZE = 512 * 1024

    def __init__(self, client, bucket: str, key: str) -> None:
        self._client = client
        self._bucket = bucket
        self._key = key
        self._pos = 0
        head = client.head_object(Bucket=bucket, Key=key)
        self._size: int = head["ContentLength"]
        self._buf = b""
        self._buf_start = 0

    def _fetch(self, start: int, length: int) -> bytes:
        end = min(start + length - 1, self._size - 1)
        if start > end:
            return b""
        r = self._client.get_object(
            Bucket=self._bucket, Key=self._key, Range=f"bytes={start}-{end}"
        )
        return r["Body"].read()

    def read(self, n: int = -1) -> bytes:
        if n == -1:
            n = self._size - self._pos
        if n <= 0:
            return b""

        buf_end = self._buf_start + len(self._buf)
        if self._pos >= self._buf_start and self._pos + n <= buf_end:
            offset = self._pos - self._buf_start
            data = self._buf[offset: offset + n]
            self._pos += len(data)
            return data

        fetch_size = max(n, self._BUFFER_SIZE)
        raw = self._fetch(self._pos, fetch_size)
        self._buf = raw
        self._buf_start = self._pos
        data = raw[:n]
        self._pos += len(data)
        return data

    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        elif whence == 2:
            self._pos = self._size + pos
        self._pos = max(0, min(self._pos, self._size))
        return self._pos

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True


def is_ignored_zip_entry(name: str) -> bool:
    """Folders and the metadata macOS adds to every archive it creates."""
    if name.endswith("/"):
        return True
    if name.startswith("__MACOSX/"):
        return True
    base = posixpath.basename(name)
    return base == ".DS_Store" or base.startswith("._")


def csv_entries(names) -> list[str]:
    """The CSV files among a ZIP's entry names, in archive order."""
    return [
        n for n in names
        if not is_ignored_zip_entry(n) and n.lower().endswith(".csv")
    ]


def zip_contents_problem(names) -> str | None:
    """Why a ZIP with these entry names is not an acceptable dataset, or None."""
    files = [n for n in names if not is_ignored_zip_entry(n)]
    if any(not n.lower().endswith(".csv") for n in files):
        return ZIP_NON_CSV
    if not files:
        return ZIP_NO_CSV
    return None


def check_uploaded_file(*, bucket_name: str, object_key: str, client=None) -> str | None:
    """Check an uploaded dataset file; returns a reason code when it must be refused.

    Whether the file is a ZIP is decided by its first bytes, not its name -
    the preview does the same, so a ZIP renamed to .csv would otherwise slip
    past the rule and still be read as an archive. Only the ZIP's central
    directory is downloaded, not the whole archive.

    A storage error is logged and lets the file through: refusing a valid
    upload over a MinIO hiccup is worse than accepting one bad archive, which
    the preview reports anyway.
    """
    named_zip = object_key.lower().endswith(".zip")
    try:
        client = client or build_minio_client()
        probe = client.get_object(Bucket=bucket_name, Key=object_key, Range="bytes=0-3")
        if not is_zip_signature(probe["Body"].read()):
            return ZIP_INVALID if named_zip else None
        if not named_zip:
            return CSV_IS_ZIP
        stream = S3SeekableStream(client, bucket_name, object_key)
        with zipfile.ZipFile(stream) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return ZIP_INVALID
    except Exception:  # botocore/network errors carry no common base class
        logger.exception("Could not inspect uploaded file '%s'; accepting it unchecked.", object_key)
        return None
    return zip_contents_problem(names)
