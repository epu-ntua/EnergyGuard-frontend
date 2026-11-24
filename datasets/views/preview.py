import csv
import io
import logging
import zipfile
import zlib

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from core.services.object_storage import MinioUploadError, build_minio_client

from ..models import Dataset
from ..services.zip_archive import S3SeekableStream, csv_entries, is_zip_signature

logger = logging.getLogger(__name__)

PREVIEW_MAX_ROWS = 50
PREVIEW_CHUNK_BYTES = 256 * 1024  # 256 KB


def _parse_csv(raw: bytes, max_rows: int) -> tuple[list, list, bool]:
    """
    The header row and up to max_rows data rows of raw CSV bytes, and whether the
    bytes hold more rows than that. Tries UTF-8, falls back to latin-1.

    The total row count is not known: only the first chunk of the file is read.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            reader = csv.reader(
                io.TextIOWrapper(io.BytesIO(raw), encoding=encoding, newline="")
            )
            headers: list = next(reader, [])
            rows: list = []
            truncated = False
            for row in reader:
                if len(rows) == max_rows:
                    truncated = True
                    break
                rows.append(row)
            return headers, rows, truncated
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not decode the file as UTF-8 or latin-1.")


def _preview_response(raw: bytes, chunk: bytes, **extra) -> JsonResponse:
    """
    The preview of `raw`, the CSV text read from `chunk`, the bytes fetched from
    storage (compressed, for a gzip file). A full chunk means the file goes on
    past it: there are more rows than the ones parsed, and the last of them may be
    cut short, so it is left out.
    """
    headers, rows, truncated = _parse_csv(raw, PREVIEW_MAX_ROWS)
    if len(chunk) >= PREVIEW_CHUNK_BYTES:
        if not truncated and rows:
            rows = rows[:-1]
        truncated = True
    return JsonResponse({"headers": headers, "rows": rows, "truncated": truncated, **extra})


def _inflate_prefix(raw: bytes) -> bytes:
    """
    Inflate as much of a truncated gzip stream as possible.

    The Range request deliberately cuts the stream mid-member, so the trailing
    bytes are incomplete; decompressobj yields everything up to that point and
    the unused tail is simply dropped.
    """
    decompressor = zlib.decompressobj(wbits=31)
    try:
        return decompressor.decompress(raw)
    except zlib.error as exc:
        raise ValueError(f"Could not decompress the gzip stream: {exc}") from exc


@login_required
def dataset_preview(request, dataset_id):
    dataset = get_object_or_404(Dataset.objects.visible_to(request.user), pk=dataset_id)

    if not dataset.data_file:
        return JsonResponse({"error": "No data file available for this dataset."}, status=404)

    try:
        client = build_minio_client()

        # Probe the first 4 bytes to detect format
        probe = client.get_object(
            Bucket=dataset.bucket_name,
            Key=dataset.data_file,
            Range="bytes=0-3",
        )
        magic = probe["Body"].read()
        is_zip = is_zip_signature(magic)

        if is_zip:
            # Seekable stream: zipfile reads only EOCD + central dir + CSV entry
            stream = S3SeekableStream(client, dataset.bucket_name, dataset.data_file)
            with zipfile.ZipFile(stream) as zf:
                csv_names = csv_entries(zf.namelist())
                if not csv_names:
                    return JsonResponse(
                        {"error": "No CSV file found inside the ZIP archive."},
                        status=422,
                    )
                with zf.open(csv_names[0]) as f:
                    raw = f.read(PREVIEW_CHUNK_BYTES)

            return _preview_response(raw, raw, source_file=csv_names[0])

        elif magic[:2] == b"\x1f\x8b":
            # gzip — not seekable, but it inflates from the start, so the first
            # chunk is far more than the handful of rows a preview needs.
            response = client.get_object(
                Bucket=dataset.bucket_name,
                Key=dataset.data_file,
                Range=f"bytes=0-{PREVIEW_CHUNK_BYTES - 1}",
            )
            compressed = response["Body"].read()
            return _preview_response(_inflate_prefix(compressed), compressed)

        else:
            # Plain CSV — Range request, no full download needed
            response = client.get_object(
                Bucket=dataset.bucket_name,
                Key=dataset.data_file,
                Range=f"bytes=0-{PREVIEW_CHUNK_BYTES - 1}",
            )
            raw = response["Body"].read()
            return _preview_response(raw, raw)

    except MinioUploadError:
        logger.exception("Storage error building preview for dataset %s", dataset_id)
        return JsonResponse({"error": "The dataset preview could not be loaded."}, status=502)
    except Exception:
        # Never echo the exception back: it carries bucket names, object keys and
        # botocore internals. Log it instead, so the operator sees more than the client.
        logger.exception("Failed to build preview for dataset %s", dataset_id)
        return JsonResponse({"error": "The dataset preview could not be loaded."}, status=500)
