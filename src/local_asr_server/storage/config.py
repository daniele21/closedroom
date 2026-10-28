"""Validated storage configuration, intentionally fail-closed until cloud integration.

This module is pure. It does not authenticate, access cloud resources, read
meeting content, or choose an upload policy. The canonical settings service
owns persisted configuration; RecordingStore will own eventual per-meeting
policy and upload state after recovery is implemented.
"""
from __future__ import annotations

import re
from typing import Any

LOCAL = "local"
PREPARATION_ONLY = "preparation_only"
_PROJECT_PATTERN = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
_BUCKET_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]\Z")
_REGION_PATTERN = re.compile(r"[a-z]+(?:-[a-z]+)*[0-9]+\Z")


def validate_storage_configuration(settings: dict[str, Any]) -> None:
    """Fail closed rather than saving settings that imply active cloud backup."""
    if settings.get("storage_mode") != LOCAL:
        raise ValueError("Cloud backup cannot be enabled until OAuth, key recovery and meeting integration are available")
    project = settings.get("gcs_project_id", "")
    bucket = settings.get("gcs_bucket_name", "")
    region = settings.get("gcs_region", "europe-west8")
    for label, value, pattern in (
        ("gcs_project_id", project, _PROJECT_PATTERN),
        ("gcs_bucket_name", bucket, _BUCKET_PATTERN),
        ("gcs_region", region, _REGION_PATTERN),
    ):
        if not isinstance(value, str) or (value != "" and pattern.fullmatch(value) is None):
            raise ValueError(f"Invalid {label}")
    if not region:
        raise ValueError("gcs_region is required")
    if bucket and (bucket.startswith("goog") or bucket.startswith("g00g")):
        raise ValueError("Reserved GCS bucket prefix")
    # Names with a dot are valid but not IP address literals.
    if bucket and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", bucket):
        raise ValueError("GCS bucket must not be an IPv4 address")


def public_storage_state(settings: dict[str, Any]) -> dict[str, Any]:
    """Report available capability separately from the configured bucket.

    Storage is not integrated: never report a GCS backup as enabled or active.
    """
    return {
        "storage_effective_mode": LOCAL,
        "storage_capability": PREPARATION_ONLY,
        "gcs_configuration_complete": bool(settings.get("gcs_project_id") and settings.get("gcs_bucket_name")),
    }
