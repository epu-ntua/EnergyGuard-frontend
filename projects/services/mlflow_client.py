import os
import secrets
from typing import Any

import requests
from django.conf import settings

from accounts.services.tokens import get_user_access_token


class MlflowClientError(Exception):
    pass


def _tracking_uri() -> str:
    return os.getenv("MLFLOW_TRACKING_URI", "https://mlflow.energy-guard.eu").rstrip("/")


def _auth_headers(user: Any | None = None) -> tuple[tuple[str, str] | None, dict[str, str]]:
    token = (get_user_access_token(user) or "").strip()

    headers: dict[str, str] = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    user: Any | None = None,
) -> dict[str, Any]:
    url = f"{_tracking_uri()}{path}"
    headers = _auth_headers(user=user)
    request_kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": 15,
    }
    if method.upper() == "GET":
        request_kwargs["params"] = params or {}
    else:
        request_kwargs["json"] = payload or {}

    try:
        print(request_kwargs)
        response = requests.request(method, url, **request_kwargs)
    except requests.RequestException as exc:
        raise MlflowClientError(f"MLflow {method} {path} request failed: {exc}") from exc
    if response.status_code >= 400:
        raise MlflowClientError(
            f"MLflow {method} {path} failed with {response.status_code}: {response.text[:400]}"
        )
    if not response.text:
        return {}
    return response.json()


def create_experiment(name: str, tags: dict[str, str] | None = None, user: Any | None = None) -> str:
    payload: dict[str, Any] = {"name": name}
    if tags:
        payload["tags"] = [{"key": str(k), "value": str(v)} for k, v in tags.items()]
    data = _request("POST", "/api/2.0/mlflow/experiments/create", payload, user=user)
    exp_id = data.get("experiment_id")
    if not exp_id:
        raise MlflowClientError("MLflow did not return experiment_id")
    return str(exp_id)


def set_experiment_tags(experiment_id: str, tags: dict[str, Any], user: Any | None = None) -> None:
    for key, value in tags.items():
        _request(
            "POST",
            "/api/2.0/mlflow/experiments/set-experiment-tag",
            {"experiment_id": str(experiment_id), "key": str(key), "value": str(value)},
            user=user,
        )


def get_experiment_tags(experiment_id: str, user: Any | None = None) -> dict[str, str]:
    data = _request(
        "GET",
        "/api/2.0/mlflow/experiments/get",
        None,
        params={"experiment_id": str(experiment_id)},
        user=user,
    )
    raw_tags = data.get("experiment", {}).get("tags", []) or []
    tags: dict[str, str] = {}
    for tag in raw_tags:
        key = tag.get("key")
        value = tag.get("value")
        if key is not None and value is not None:
            tags[str(key)] = str(value)
    return tags


def delete_experiment(experiment_id: str, user: Any | None = None) -> None:
    _request("POST", "/api/2.0/mlflow/experiments/delete", {"experiment_id": str(experiment_id)}, user=user)


def update_experiment_name(experiment_id: str, new_name: str, user: Any | None = None) -> None:
    _request(
        "POST",
        "/api/2.0/mlflow/experiments/update",
        {"experiment_id": str(experiment_id), "new_name": str(new_name)},
        user=user,
    )


def list_experiment_runs(
    experiment_id: str, max_results: int = 25, user: Any | None = None
) -> list[dict[str, Any]]:
    payload = {
        "experiment_ids": [str(experiment_id)],
        "max_results": max_results,
        "order_by": ["attributes.start_time DESC"],
    }
    data = _request("POST", "/api/2.0/mlflow/runs/search", payload, user=user)
    return data.get("runs", []) or []


def list_run_artifacts(run_id: str, path: str = "", user: Any | None = None) -> list[dict[str, Any]]:
    data = _request(
        "GET",
        "/api/2.0/mlflow/artifacts/list",
        None,
        params={"run_id": str(run_id), "path": path},
        user=user,
    )
    return data.get("files", []) or []


def get_run(run_id: str, user: Any | None = None) -> dict[str, Any]:
    data = _request(
        "GET",
        "/api/2.0/mlflow/runs/get",
        None,
        params={"run_id": str(run_id)},
        user=user,
    )
    return data.get("run", {}) or {}


def _setting(primary: str, fallback: str = "", default: Any = None) -> Any:
    if hasattr(settings, primary):
        return getattr(settings, primary)
    if fallback and hasattr(settings, fallback):
        return getattr(settings, fallback)
    return default

def delete_artifacts_from_object_storage(experiment_id: str) -> None:
    experiment = str(experiment_id or "").strip().strip("/")
    if not experiment:
        return

    access_key = getattr(settings, "OBJECT_STORAGE_ACCESS_KEY", "") or getattr(settings, "MINIO_ACCESS_KEY", "")
    secret_key = getattr(settings, "OBJECT_STORAGE_SECRET_KEY", "") or getattr(settings, "MINIO_SECRET_KEY", "")
    endpoint = getattr(settings, "OBJECT_STORAGE_ENDPOINT", None) or getattr(settings, "MINIO_ENDPOINT", None)
    verify_ssl = getattr(settings, "OBJECT_STORAGE_VERIFY_SSL", None)
    if verify_ssl is None:
        verify_ssl = getattr(settings, "MINIO_VERIFY_SSL", True)

    if not access_key or not secret_key:
        raise MlflowClientError("Object storage credentials are missing.")

    try:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            verify=verify_ssl,
        )

        bucket_name = "mlflow-bucket"
        prefix = f"{experiment}/"
        continuation_token = None
        while True:
            request = {"Bucket": bucket_name, "Prefix": prefix}
            if continuation_token:
                request["ContinuationToken"] = continuation_token

            page = client.list_objects_v2(**request)
            contents = page.get("Contents") or []
            for start in range(0, len(contents), 1000):
                batch = contents[start : start + 1000]
                keys = [{"Key": obj["Key"]} for obj in batch if obj.get("Key")]
                print("keys", keys)
                if keys:
                    client.delete_objects(Bucket=bucket_name, Delete={"Objects": keys})

            if not page.get("IsTruncated"):
                break
            continuation_token = page.get("NextContinuationToken")
    except Exception as exc:
        raise MlflowClientError(f"Artifact cleanup failed for experiment {experiment}: {exc}") from exc


def make_deleted_experiment_name() -> str:
    return f"deleted-{secrets.token_hex(8)}"
