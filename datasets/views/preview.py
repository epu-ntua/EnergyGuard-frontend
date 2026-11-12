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

            headers, rows = _parse_csv(raw, PREVIEW_MAX_ROWS)
            return JsonResponse({"headers": headers, "rows": rows, "source_file": csv_names[0]})

        elif magic[:2] == b"\x1f\x8b":
            # gzip — not seekable, but it inflates from the start, so the first
            # chunk is far more than the handful of rows a preview needs.
            response = client.get_object(
                Bucket=dataset.bucket_name,
                Key=dataset.data_file,
                Range=f"bytes=0-{PREVIEW_CHUNK_BYTES - 1}",
            )
            raw = _inflate_prefix(response["Body"].read())
            headers, rows = _parse_csv(raw, PREVIEW_MAX_ROWS)
            return JsonResponse({"headers": headers, "rows": rows})

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

    except MinioUploadError:
        logger.exception("Storage error building preview for dataset %s", dataset_id)
        return JsonResponse({"error": "The dataset preview could not be loaded."}, status=502)
    except Exception:
        # Never echo the exception back: it carries bucket names, object keys and
        # botocore internals. Log it instead, so the operator sees more than the client.
        logger.exception("Failed to build preview for dataset %s", dataset_id)
        return JsonResponse({"error": "The dataset preview could not be loaded."}, status=500)
