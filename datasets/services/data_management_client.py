import logging
from urllib.parse import quote

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.DATA_MANAGEMENT_SERVER_API_KEY,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return settings.DATA_MANAGEMENT_SERVER_URL


def provision_user_datasets(username: str, datasets: dict[str, str]) -> None:
    """
    POST /api/v1/provision/user

    datasets: {minio_prefix: local_name}
    """
    try:
        response = requests.post(
            f"{_base_url()}/api/v1/provision/user",
            headers=_headers(),
            json={
                "username": username,
                "datasets": datasets,
                "notebooks": None,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("JupyterHub provision failed for user %s: %s", username, exc)
        raise


def provision_pilot_dataset(
    username: str, partner: str, dataset_local_name: str
) -> None:
    """
    POST /api/v1/provision/pilot

    Pilot datasets have no MinIO object to copy, so provisioning works the other
    way round from provision_user_datasets: the dashboard only announces which
    partner's data the user wants, and the data management server pulls it out
    of the data lake itself and writes it into the user's datasets folder.
    """
    try:
        response = requests.post(
            f"{_base_url()}/api/v1/provision/pilot",
            headers=_headers(),
            json={
                "username": username,
                "partner": partner.upper(),
                "dataset_name": dataset_local_name,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error(
            "Pilot provision failed for user %s (partner %s): %s",
            username,
            partner,
            exc,
        )
        raise


def delete_dataset_cache(username: str, dataset_local_name: str) -> None:
    """
    DELETE /api/v1/datasets/cache/{username}/{dataset_local_name}
    """
    encoded_username = quote(str(username), safe="")
    encoded_name = quote(str(dataset_local_name), safe="")
    try:
        response = requests.delete(
            f"{_base_url()}/api/v1/datasets/cache/{encoded_username}/{encoded_name}",
            headers=_headers(),
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error(
            "Cache delete failed for dataset '%s' (user %s): %s",
            dataset_local_name,
            username,
            exc,
        )
        raise


def sync_jupyterhub(
    username: str,
    before: dict[str, str],
    after: dict[str, str],
) -> None:
    """
    Diff-based JupyterHub sync.

    - added datasets   → provision_user_datasets
    - removed datasets → delete_dataset_cache
    """
    added = {k: v for k, v in after.items() if k not in before}
    removed = {k: v for k, v in before.items() if k not in after}

    if not added and not removed:
        return

    if added:
        try:
            provision_user_datasets(username, added)
        except requests.RequestException:
            pass  # already logged in provision_user_datasets

    for local_name in removed.values():
        try:
            delete_dataset_cache(username, local_name)
        except requests.RequestException:
            pass  # already logged in delete_dataset_cache
