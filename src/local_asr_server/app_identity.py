"""Runtime identity helpers for the ClosedRoom app and bundled server."""

from __future__ import annotations

import os
import plistlib
from dataclasses import dataclass
from importlib import metadata

from local_asr_server import __version__
from local_asr_server.paths import (
    APP_BUNDLE_ID,
    APP_NAME,
    get_app_contents_dir,
    is_bundled,
)


@dataclass(frozen=True)
class AppIdentity:
    name: str
    version: str
    bundle_identifier: str
    display_name: str
    bundled: bool
    pid: int

    def as_health_payload(self) -> dict:
        return {
            "app_name": self.name,
            "app_version": self.version,
            "bundle_identifier": self.bundle_identifier,
            "bundle_display_name": self.display_name,
            "bundled": self.bundled,
            "pid": self.pid,
        }


def _bundle_info() -> dict:
    contents_dir = get_app_contents_dir()
    if contents_dir is None:
        return {}

    info_plist = contents_dir / "Info.plist"
    try:
        with info_plist.open("rb") as f:
            payload = plistlib.load(f)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_bundle_display_name() -> str:
    """Return the visible bundle name from Info.plist when bundled."""
    payload = _bundle_info()
    value = payload.get("CFBundleDisplayName") or payload.get("CFBundleName")
    return str(value or APP_NAME)


def get_bundle_identifier() -> str:
    """Return the bundle identifier from Info.plist when bundled."""
    payload = _bundle_info()
    value = payload.get("CFBundleIdentifier")
    return str(value or APP_BUNDLE_ID)


def get_bundle_version() -> str | None:
    """Return the product version embedded in the macOS bundle, when available."""
    payload = _bundle_info()
    value = payload.get("CFBundleShortVersionString") or payload.get("CFBundleVersion")
    text = str(value or "").strip()
    return text or None


def get_app_version() -> str:
    """Return the product identity version for bundled apps, package version otherwise.

    ClosedRoom's root VERSION owns the macOS product version and is embedded in
    Info.plist at build time. The Python distribution has an independent package
    version, so a frozen app must not expose that package version as its runtime
    application identity.
    """
    if is_bundled():
        bundle_version = get_bundle_version()
        if bundle_version:
            return bundle_version
    try:
        return metadata.version("local-asr-server")
    except metadata.PackageNotFoundError:
        return __version__


def get_app_identity() -> AppIdentity:
    """Return the current process identity used to detect stale app servers."""
    return AppIdentity(
        name=APP_NAME,
        version=get_app_version(),
        bundle_identifier=get_bundle_identifier(),
        display_name=get_bundle_display_name(),
        bundled=is_bundled(),
        pid=os.getpid(),
    )
