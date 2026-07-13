from typing import Any

from django.conf import settings


class MinioUploadError(RuntimeError):
    pass


def _setting(primary: str, fallback: str = "", default: Any = None):
    if hasattr(settings, primary):
        return getattr(settings, primary)
    if fallback and hasattr(settings, fallback):
        return getattr(settings, fallback)
    return default


def build_minio_client():
    access_key = _setting("OBJECT_STORAGE_ACCESS_KEY", "MINIO_ACCESS_KEY", default="")
    secret_key = _setting("OBJECT_STORAGE_SECRET_KEY", "MINIO_SECRET_KEY", default="")
    endpoint = _setting("OBJECT_STORAGE_ENDPOINT", "MINIO_ENDPOINT")
    verify_ssl = _setting("OBJECT_STORAGE_VERIFY_SSL", "MINIO_VERIFY_SSL", default=True)

    if not access_key or not secret_key:
        raise MinioUploadError("MINIO credentials are missing in environment settings.")

    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise MinioUploadError("boto3 is not installed.") from exc

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        verify=verify_ssl,
        config=Config(connect_timeout=10, read_timeout=60),
    )


def object_exists(*, bucket_name: str, object_key: str) -> bool:
    """Return True if the object exists in MinIO, False if not found."""
    from botocore.exceptions import ClientError

    client = build_minio_client()
    try:
        client.head_object(Bucket=bucket_name, Key=object_key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise MinioUploadError(str(exc)) from exc


def put_object(*, bucket_name: str, object_key: str, body: bytes, content_type: str) -> None:
    """Upload an in-memory payload directly to MinIO (no multipart transfer)."""
    from botocore.exceptions import BotoCoreError, ClientError

    client = build_minio_client()
    try:
        client.put_object(Bucket=bucket_name, Key=object_key, Body=body, ContentType=content_type)
    except (ClientError, BotoCoreError) as exc:
        raise MinioUploadError(str(exc)) from exc
