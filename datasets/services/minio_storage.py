from typing import Any
from uuid import uuid4

try:
    from boto3.s3.transfer import TransferConfig as S3TransferConfig

    _TRANSFER_CONFIG = S3TransferConfig(
        multipart_threshold=16 * 1024 * 1024,
        multipart_chunksize=16 * 1024 * 1024,
        max_concurrency=8,
    )
except ImportError:
    _TRANSFER_CONFIG = None

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


def _build_minio_client():
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


# Utility function to create a safe slug from a string, with a fallback if the result is empty
def _safe_name(value: str, fallback: str) -> str:
    normalized = slugify(value or "")
    return normalized or fallback


def upload_dataset_objects(
    *,
    user_name: str,
    dataset_name: str,
    data_file,
) -> dict[str, str]:
    bucket_name = _setting("OBJECT_STORAGE_BUCKET", "MINIO_BUCKET_DATASETS", default="datasets")

    user_part = user_name or "user"
    dataset_part = _safe_name(dataset_name, "dataset")
    dataset_uid = uuid4().hex[:8]
    root_prefix = f"user_{user_part}/dataset_{dataset_part}_{dataset_uid}"

    data_filename = data_file.name.split("/")[-1].split("\\")[-1]
    data_key = f"{root_prefix}/{data_filename}"

    client = _build_minio_client()

    try:
        from botocore.exceptions import BotoCoreError, ClientError

        data_file.seek(0)
        client.upload_fileobj(
            Fileobj=data_file,
            Bucket=bucket_name,
            Key=data_key,
            ExtraArgs={"ContentType": data_file.content_type or "application/octet-stream"},
            Config=_TRANSFER_CONFIG,
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchBucket":
            raise MinioUploadError(
                f"Storage bucket '{bucket_name}' does not exist. Contact the administrator."
            ) from exc
        raise MinioUploadError(str(exc)) from exc
    except BotoCoreError as exc:
        raise MinioUploadError(str(exc)) from exc

    return {
        "bucket_name": bucket_name,
        "data_file_key": data_key,
    }


def delete_dataset_objects(
    *,
    bucket_name: str,
    data_file_key: str,
    metadata_file_key: str = "",
) -> None:
    object_keys = [key for key in {data_file_key, metadata_file_key} if key]
    if not object_keys:
        return

    client = _build_minio_client()

    try:
        from botocore.exceptions import BotoCoreError, ClientError

        response = client.delete_objects(
            Bucket=bucket_name,
            Delete={
                "Objects": [{"Key": key} for key in object_keys],
                "Quiet": True,
            },
        )

        failed = response.get("Errors", [])
        if failed:
            failed_keys = ", ".join(e.get("Key", "") for e in failed)
            raise MinioUploadError(
                f"Failed to delete the following objects from bucket '{bucket_name}': {failed_keys}"
            )
    except (ClientError, BotoCoreError) as exc:
        raise MinioUploadError(str(exc)) from exc
