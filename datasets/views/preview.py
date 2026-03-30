import csv
import io
import zipfile

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from ..models import Dataset
from ..services.minio_storage import MinioUploadError, _build_minio_client, _is_fake_upload_enabled

PREVIEW_MAX_ROWS = 50
PREVIEW_CHUNK_BYTES = 256 * 1024  # 256 KB


class _S3SeekableStream:
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


def _parse_csv(raw: bytes, max_rows: int) -> tuple[list, list]:
    """Parse up to max_rows from raw CSV bytes. Tries UTF-8, falls back to latin-1."""
    for encoding in ("utf-8", "latin-1"):
        try:
            reader = csv.reader(
                io.TextIOWrapper(io.BytesIO(raw), encoding=encoding, newline="")
            )
            headers: list = []
            rows: list = []
            for i, row in enumerate(reader):
                if i == 0:
                    headers = row
                else:
                    rows.append(row)
                if i > max_rows:
                    break
            return headers, rows
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the file as UTF-8 or latin-1.")


@login_required
def dataset_preview(request, dataset_id):
    dataset = get_object_or_404(Dataset, pk=dataset_id)

    if not dataset.data_file:
        return JsonResponse({"error": "No data file available for this dataset."}, status=404)

    if _is_fake_upload_enabled():
        headers = ["timestamp", "energy_kwh", "voltage_v", "current_a", "source"]
        rows = [
            [f"2024-01-{i:02d} 08:00:00", str(round(i * 12.4, 2)), "230", str(round(i * 0.54, 2)), "sensor_A"]
            for i in range(1, 11)
        ]
        return JsonResponse({"headers": headers, "rows": rows})

    try:
        client = _build_minio_client()

        # Probe the first 4 bytes to detect format
        probe = client.get_object(
            Bucket=dataset.bucket_name,
            Key=dataset.data_file,
            Range="bytes=0-3",
        )
        magic = probe["Body"].read()
        is_zip = magic[:4] == b"PK\x03\x04"

        if is_zip:
            # Seekable stream: zipfile reads only EOCD + central dir + CSV entry
            stream = _S3SeekableStream(client, dataset.bucket_name, dataset.data_file)
            with zipfile.ZipFile(stream) as zf:
                csv_names = [
                    n for n in zf.namelist()
                    if n.lower().endswith(".csv") and not n.startswith("__MACOSX")
                ]
                if not csv_names:
                    return JsonResponse(
                        {"error": "No CSV file found inside the ZIP archive."},
                        status=422,
                    )
                with zf.open(csv_names[0]) as f:
                    raw = f.read(PREVIEW_CHUNK_BYTES)

            headers, rows = _parse_csv(raw, PREVIEW_MAX_ROWS)
            return JsonResponse({"headers": headers, "rows": rows, "source_file": csv_names[0]})

        else:
            # Plain CSV — Range request, no full download needed
            response = client.get_object(
                Bucket=dataset.bucket_name,
                Key=dataset.data_file,
                Range=f"bytes=0-{PREVIEW_CHUNK_BYTES - 1}",
            )
            raw = response["Body"].read()
            headers, rows = _parse_csv(raw, PREVIEW_MAX_ROWS)
            return JsonResponse({"headers": headers, "rows": rows})

    except MinioUploadError as exc:
        return JsonResponse({"error": str(exc)}, status=500)
    except Exception as exc:
        return JsonResponse({"error": f"{type(exc).__name__}: {exc}"}, status=500)
