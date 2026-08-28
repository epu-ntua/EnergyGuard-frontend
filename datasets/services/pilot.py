"""
Conventions for pilot datasets.

Pilot data belongs to the platform, not to a user. The data management server
refreshes it daily out of the CARTIF data lake and writes one gzipped CSV per
partner into MinIO:

    <datasets bucket>/pilot_datasets/<PARTNER>/<PARTNER>.csv.gz

From the dashboard's point of view a pilot dataset is then an ordinary
MinIO-backed dataset — preview and download read that object like any other.
The only thing that differs is JupyterHub provisioning: instead of copying the
file into the user's folder, the data management server mounts the single
shared copy read-only.
"""

from django.conf import settings

from .datalake import PARTNER_DATABASES

# Every partner that has pilot data. Kept in sync with PARTNER_DATABASES by a
# test, so adding a partner in one place fails loudly if the other is missed.
PILOT_PARTNERS = tuple(PARTNER_DATABASES)


def pilot_prefix() -> str:
    """Bucket-relative folder holding every partner's pilot dataset."""
    return getattr(settings, "PILOT_DATASETS_PREFIX", "pilot_datasets").strip("/")


def pilot_object_key(partner: str) -> str:
    """The MinIO key of one partner's pilot CSV."""
    name = partner.strip().upper()
    return f"{pilot_prefix()}/{name}/{name}.csv.gz"


def pilot_object_folder(partner: str) -> str:
    """The MinIO folder holding one partner's pilot dataset."""
    return f"{pilot_prefix()}/{partner.strip().upper()}"


def pilot_partner_for(dataset) -> str | None:
    """
    Return the pilot partner a Dataset belongs to, or None for a regular
    user-uploaded dataset.

    Two ways to mark a dataset as pilot data, checked in order:
      1. ``metadata["pilot_partner"]`` — explicit, wins over everything.
      2. a ``data_file`` key under ``pilot_datasets/<PARTNER>/``.
    """
    metadata = dataset.metadata
    if isinstance(metadata, dict):
        declared = metadata.get("pilot_partner")
        if declared:
            name = str(declared).strip().upper()
            if name in PILOT_PARTNERS:
                return name

    parts = (dataset.data_file or "").split("/")
    if len(parts) >= 2 and parts[0] == pilot_prefix():
        name = parts[1].strip().upper()
        if name in PILOT_PARTNERS:
            return name

    return None
