import json
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.utils.text import slugify


class MinioUploadError(RuntimeError):
    pass


def _setting(primary: str, fallback: str = "", default: Any = None):
    if hasattr(settings, primary):
        return getattr(settings, primary)
    if fallback and hasattr(settings, fallback):
        return getattr(settings, fallback)
    return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _is_fake_upload_enabled() -> bool:
    return _to_bool(_setting("OBJECT_STORAGE_FAKE_UPLOAD", "MINIO_FAKE_UPLOAD", default=False))


def _build_minio_client():
    access_key = _setting("OBJECT_STORAGE_ACCESS_KEY", "MINIO_ACCESS_KEY", default="")
    secret_key = _setting("OBJECT_STORAGE_SECRET_KEY", "MINIO_SECRET_KEY", default="")
    endpoint = _setting("OBJECT_STORAGE_ENDPOINT", "MINIO_ENDPOINT")
    region = _setting("OBJECT_STORAGE_REGION", "MINIO_REGION", default="us-east-1")
    verify_ssl = _setting("OBJECT_STORAGE_VERIFY_SSL", "MINIO_VERIFY_SSL", default=True)

    if not access_key or not secret_key:
        raise MinioUploadError("MINIO credentials are missing in environment settings.")

    try:
        import boto3
    except ImportError as exc:
        raise MinioUploadError("boto3 is not installed.") from exc

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        verify=verify_ssl,
    )


# Utility function to create a safe slug from a string, with a fallback if the result is empty
def _safe_name(value: str, fallback: str) -> str:
    normalized = slugify(value or "")
    return normalized or fallback


def upload_dataset_objects(
    *,
    user_name: str,
    dataset_name: str,
    data_file,
    metadata_file=None,
    metadata_json: Any = None,
) -> dict[str, str]:
    bucket_name = _setting("OBJECT_STORAGE_BUCKET", "MINIO_BUCKET_DATASETS", default="datasets")

    user_part = _safe_name(user_name, "user")
    dataset_part = _safe_name(dataset_name, "dataset")
    dataset_uid = uuid4().hex[:8]
    root_prefix = f"user_{user_part}/dataset_{dataset_part}_{dataset_uid}"

    data_filename = data_file.name.split("/")[-1].split("\\")[-1]
    data_key = f"{root_prefix}/{data_filename}"
    metadata_key = ""

    if metadata_file:
        metadata_filename = metadata_file.name.split("/")[-1].split("\\")[-1]
        metadata_key = f"{root_prefix}/{metadata_filename}"
    elif metadata_json:
        metadata_key = f"{root_prefix}/metadata.json"

    # Local development mode: skip actual object storage upload.
    if _is_fake_upload_enabled():
        return {
            "bucket_name": bucket_name,
            "data_file_key": data_key,
            "metadata_file_key": metadata_key,
        }

    client = _build_minio_client()

    try:
        from botocore.exceptions import BotoCoreError, ClientError

        data_file.seek(0)
        client.upload_fileobj(
            Fileobj=data_file,
            Bucket=bucket_name,
            Key=data_key,
            ExtraArgs={"ContentType": data_file.content_type or "application/octet-stream"},
        )

        if metadata_file:
            metadata_file.seek(0)
            client.upload_fileobj(
                Fileobj=metadata_file,
                Bucket=bucket_name,
                Key=metadata_key,
                ExtraArgs={"ContentType": metadata_file.content_type or "application/json"},
            )
        elif metadata_json:
            metadata_body = json.dumps(metadata_json, ensure_ascii=False, indent=2).encode("utf-8")
            client.put_object(
                Bucket=bucket_name,
                Key=metadata_key,
                Body=metadata_body,
                ContentType="application/json",
            )
    except (ClientError, BotoCoreError) as exc:
        raise MinioUploadError(str(exc)) from exc

    return {
        "bucket_name": bucket_name,
        "data_file_key": data_key,
        "metadata_file_key": metadata_key,
    }
