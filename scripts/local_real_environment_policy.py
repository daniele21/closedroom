#!/usr/bin/env python3
"""Local-only artifact qualification for ClosedRoom REAL_ENVIRONMENT evidence.

This module deliberately does not alter the production release policy. It is
used only by the explicit local REAL_ENVIRONMENT adapter when Apple distribution
authority is unavailable. Accepted artifacts must be exact-revision, finalized,
clean, local Apple-Silicon builds using ad-hoc signing.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from finalize_build_artifact import fingerprint_tree

INSTALLED_APP_ENV = "CLOSEDROOM_LOCAL_REAL_ENVIRONMENT_INSTALLED_APP"
SOURCE_APP_ENV = "CLOSEDROOM_LOCAL_REAL_ENVIRONMENT_SOURCE_APP"
MAIN_APP_ENV = "CLOSEDROOM_LOCAL_REAL_ENVIRONMENT_MAIN_APP"



def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read local build manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid local build manifest: {path}")
    return payload


def local_manifest_for(
    app: Path, *, allow_identified: bool = False
) -> tuple[Path, dict[str, Any]]:
    """Validate one finalized ad-hoc artifact for local physical evidence only."""
    manifest_path = app.parent / "build-manifest.json"
    if not manifest_path.is_file():
        installed = os.environ.get(INSTALLED_APP_ENV)
        original = os.environ.get(SOURCE_APP_ENV)
        if not installed or not original or app.absolute() != Path(installed).absolute():
            raise RuntimeError("local app is missing build-manifest.json")
        source_app = Path(original).expanduser().absolute()
        if source_app == app.absolute():
            raise RuntimeError("installed and source app must be separate paths")
        is_main_app = os.environ.get(MAIN_APP_ENV) == "1"
        original_manifest, manifest = local_manifest_for(
            source_app, allow_identified=is_main_app
        )
        verify_installed_copy(app, manifest)
        return original_manifest, manifest

    manifest = read_json(manifest_path)
    if manifest.get("status") != "successful":
        raise RuntimeError("local build manifest is not successful")

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    if bool(source.get("dirty")):
        raise RuntimeError("local REAL_ENVIRONMENT artifact was built from a dirty checkout")

    configuration = (
        manifest.get("configuration")
        if isinstance(manifest.get("configuration"), dict)
        else {}
    )
    signing = str(configuration.get("signing") or "")
    if signing not in ({"ad-hoc", "identified"} if allow_identified else {"ad-hoc"}):
        raise RuntimeError(
            "local REAL_ENVIRONMENT requires an ad-hoc artifact except for "
            "the explicitly selected verified main app; "
            f"manifest signing is {signing or 'unknown'}"
        )

    lineage = manifest.get("lineage") if isinstance(manifest.get("lineage"), dict) else {}
    if lineage.get("platform") != "macos" or lineage.get("architecture") != "arm64":
        raise RuntimeError("local REAL_ENVIRONMENT artifact is not macOS arm64")

    validation = (
        manifest.get("validation") if isinstance(manifest.get("validation"), dict) else {}
    )
    if validation.get("build") != "pass" or validation.get("codesign") != "pass":
        raise RuntimeError("local REAL_ENVIRONMENT artifact lacks finalized build/codesign proof")

    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), dict) else {}
    app_metadata = artifacts.get("app") if isinstance(artifacts.get("app"), dict) else {}
    if str(app_metadata.get("path") or "") != app.name:
        raise RuntimeError("local REAL_ENVIRONMENT app does not match build manifest")

    return manifest_path, manifest


def verify_installed_copy(app: Path, manifest: dict[str, Any]) -> None:
    """Reject altered/partial installed bundles; keep the finalized source authoritative."""
    if app.is_symlink() or not app.is_dir():
        raise RuntimeError("installed test application is not a real app directory")
    expected = ((manifest.get("artifacts") or {}).get("app") or {})
    expected_sha = str(expected.get("sha256") or "")
    if not expected_sha or not isinstance(expected.get("file_count"), int):
        raise RuntimeError("installed app requires finalized SHA-256 and file-count evidence")
    actual = fingerprint_tree(app)
    if actual["sha256"] != expected_sha or actual["file_count"] != expected["file_count"]:
        raise RuntimeError("installed test app differs from immutable finalized artifact")
    if isinstance(expected.get("bytes"), int) and actual["bytes"] != expected["bytes"]:
        raise RuntimeError("installed test app size differs from immutable finalized artifact")


def install_test_app(
    source_app: Path,
    manifest: dict[str, Any],
    *,
    applications_dir: Path = Path("/Applications"),
) -> tuple[Path, str]:
    """Copy one immutable, validated local app into /Applications for TCC testing.

    Never overwrite an existing app, never alter the source artifact, never sudo.
    Same exact build is reused; differing builds have distinct app names.
    """
    source_app = source_app.expanduser().absolute()
    manifest_path, validated = local_manifest_for(source_app)
    if manifest != validated:
        raise RuntimeError("source manifest changed during test-app installation")
    verify_installed_copy(source_app, validated)

    source = validated.get("source") or {}
    revision = str(source.get("revision") or "")[:12]
    build_id = str(validated.get("build_id") or "")
    if not revision or not build_id:
        raise RuntimeError("test installation requires exact revision and build ID")
    safe_build_id = re.sub(r"[^A-Za-z0-9._-]", "-", build_id)[:90]
    destination = applications_dir / f"ClosedRoom Test-{revision}-{safe_build_id}.app"
    if not applications_dir.is_dir():
        raise RuntimeError(f"Applications directory missing: {applications_dir}")

    if destination.exists() or destination.is_symlink():
        verify_installed_copy(destination, validated)
        return destination, "reused_verified"

    temporary = applications_dir / f".ClosedRoom-Test-install-{secrets.token_hex(8)}.app"
    try:
        subprocess.run(["ditto", str(source_app), str(temporary)], check=True, timeout=900)
        verify_installed_copy(temporary, validated)
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(temporary)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if destination.exists() or destination.is_symlink():
            raise RuntimeError(f"test app destination appeared during installation: {destination}")
        temporary.rename(destination)
    finally:
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
    return destination, "installed_verified"


def install_main_app(
    source_app: Path,
    manifest: dict[str, Any],
    *,
    applications_dir: Path = Path("/Applications"),
) -> Path:
    """Install one exact locally identified candidate as the real ClosedRoom.app.

    Explicit opt-in only: must not replace existing files, folders or symlinks.
    The source artifact remains immutable and a failed copy leaves no main app.
    """
    source_app = source_app.expanduser().absolute()
    _, verified = local_manifest_for(source_app, allow_identified=True)
    if manifest != verified or (verified.get("configuration") or {}).get("signing") != "identified":
        raise RuntimeError("main app installation requires the exact identified build manifest")
    if (verified.get("configuration") or {}).get("bundle_id") != "com.closedroom.app":
        raise RuntimeError("main app installation requires com.closedroom.app bundle identity")
    verify_installed_copy(source_app, verified)
    with (source_app / "Contents" / "Info.plist").open("rb") as stream:
        bundle_info = plistlib.load(stream)
    if bundle_info.get("CFBundleIdentifier") != "com.closedroom.app":
        raise RuntimeError("source bundle identity is not com.closedroom.app")

    target = applications_dir / "ClosedRoom.app"
    if not applications_dir.is_dir():
        raise RuntimeError(f"Applications directory missing: {applications_dir}")
    if target.exists() or target.is_symlink():
        raise RuntimeError(
            f"main app destination already exists: {target}; refusing to replace it"
        )
    temporary = applications_dir / f".ClosedRoom-main-install-{secrets.token_hex(8)}.app"
    try:
        subprocess.run(["ditto", str(source_app), str(temporary)], check=True, timeout=900)
        verify_installed_copy(temporary, verified)
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(temporary)],
            check=True, capture_output=True, text=True, timeout=120,
        )
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"destination appeared during install: {target}")
        temporary.rename(target)
    finally:
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
    verify_installed_copy(target, verified)
    return target



def signing_authorities(app: Path) -> tuple[str, ...]:
    """Match the existing app's certificate chain to the newly signed candidate."""
    result = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(app)],
        check=True, capture_output=True, text=True, timeout=120,
    )
    output = "\n".join((result.stdout, result.stderr))
    authorities = tuple(
        line.partition("=")[2].strip()
        for line in output.splitlines()
        if line.startswith("Authority=") and line.partition("=")[2].strip()
    )
    if not authorities:
        raise RuntimeError("main app upgrade requires identifiable certificate authority (not ad-hoc)")
    return authorities


def main_app_running(app: Path) -> bool:
    """Check the exact installed executable, not unrelated ClosedRoom test apps."""
    expected = str(app / "Contents" / "MacOS" / "ClosedRoom")
    result = subprocess.run(
        ["ps", "-axo", "command="],
        check=True, capture_output=True, text=True, timeout=30,
    )
    return any(
        command.strip() == expected or command.strip().startswith(expected + " ")
        for command in result.stdout.splitlines()
    )


def upgrade_main_app(
    source_app: Path,
    manifest: dict[str, Any],
    *,
    applications_dir: Path = Path("/Applications"),
) -> tuple[Path, Path]:
    """Explicit upgrade of main app: stage verified build, preserve old, rollback on error.

    This never deletes the previous app. Backup is kept in /Applications and
    reported to the operator, but hidden to avoid duplicate LaunchServices apps.
    The real native app must be closed before any rename.
    """
    target = applications_dir / "ClosedRoom.app"
    if target.is_symlink() or not target.is_dir():
        raise RuntimeError(f"cannot upgrade missing/symlink main app: {target}")
    with (target / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info.get("CFBundleIdentifier") != "com.closedroom.app":
        raise RuntimeError("cannot upgrade app with unexpected bundle identifier")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(target)],
        check=True, capture_output=True, text=True, timeout=120,
    )
    if main_app_running(target):
        raise RuntimeError("quit the existing /Applications/ClosedRoom.app before upgrading")
    original_authorities = signing_authorities(target)
    existing_fingerprint = fingerprint_tree(target)

    # The canonical main-app installation owner verifies the source/manifest,
    # signed staging bundle, and exact tree before any installed app is touched.
    token = secrets.token_hex(8)
    staging_dir = applications_dir / f".ClosedRoom-upgrade-staging-{token}"
    backup = applications_dir / f".ClosedRoom-backup-{token}.app"
    failed_candidate = applications_dir / f".ClosedRoom-failed-upgrade-{token}.app"
    if staging_dir.exists() or backup.exists() or failed_candidate.exists():
        raise RuntimeError("main app upgrade generated a conflicting staging/backup path")
    staging_dir.mkdir()
    try:
        staged = install_main_app(
            source_app, manifest, applications_dir=staging_dir,
        )
        if signing_authorities(staged) != original_authorities:
            raise RuntimeError(
                "new app signing authority differs from installed ClosedRoom; "
                "old app preserved and TCC continuity cannot be assumed"
            )
        if main_app_running(target):
            raise RuntimeError("existing ClosedRoom started during upgrade; close it")
        if fingerprint_tree(target) != existing_fingerprint:
            raise RuntimeError("existing main app changed during staging; nothing replaced")
        # Backup is the complete, signed original app, on the same volume.
        target.rename(backup)
        try:
            if target.exists() or target.is_symlink():
                raise RuntimeError("main app destination occupied during upgrade")
            staged.rename(target)
            verify_installed_copy(target, manifest)
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", str(target)],
                check=True, capture_output=True, text=True, timeout=120,
            )
        except Exception:
            # Preserve the failed candidate instead of deleting unknown content.
            if target.is_dir() and not target.is_symlink():
                target.rename(failed_candidate)
            if not target.exists() and not target.is_symlink() and backup.is_dir():
                backup.rename(target)
            raise
    finally:
        if staging_dir.is_dir() and not staging_dir.is_symlink():
            shutil.rmtree(staging_dir)
    return target, backup


def installed_main_artifact(
    root: Path,
    revision: str,
    *,
    installed_app: Path = Path("/Applications/ClosedRoom.app"),
) -> tuple[Path, Path, Path, dict[str, Any]]:
    """Match existing real /Applications app to one immutable exact-HEAD build.

    Read only: never replace, sign, move, or launch the user's installed app.
    Identified local builds qualify for physical tests but not release distribution.
    """
    if not installed_app.is_dir() or installed_app.is_symlink():
        raise RuntimeError(f"main ClosedRoom app missing or symlink: {installed_app}")
    with (installed_app / "Contents" / "Info.plist").open("rb") as stream:
        bundle_info = plistlib.load(stream)
    if bundle_info.get("CFBundleIdentifier") != "com.closedroom.app":
        raise RuntimeError("installed main app does not have com.closedroom.app bundle identity")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(installed_app)],
        check=True, capture_output=True, text=True, timeout=120,
    )

    for candidate in (root / "dist" / "artifacts").glob("*/*/build-manifest.json"):
        try:
            data = read_json(candidate)
            src = data.get("source") if isinstance(data.get("source"), dict) else {}
            if not revisions_match(revision, str(src.get("revision") or "")):
                continue
            name = str(((data.get("artifacts") or {}).get("app") or {}).get("path") or "")
            if not name:
                continue
            source_app = candidate.parent / name
            if not source_app.is_dir():
                continue
            _, manifest = local_manifest_for(source_app, allow_identified=True)
            config = manifest.get("configuration") or {}
            if config.get("bundle_id", "com.closedroom.app") != "com.closedroom.app":
                continue
            verify_installed_copy(installed_app, manifest)
            return installed_app, source_app, candidate, manifest
        except (OSError, ValueError, RuntimeError):
            continue

    raise RuntimeError(
        "The existing /Applications/ClosedRoom.app does not match any finalized, "
        "clean artifact for this exact Git revision. Nothing was replaced. "
        "Install the exact candidate with your stable signing identity first, "
        "or use the separate test-app mode."
    )


def revisions_match(left: str, right: str) -> bool:
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def find_exact_local_app(root: Path, revision: str) -> tuple[Path, Path, dict[str, Any]] | None:
    """Return the newest exact-revision finalized ad-hoc app, if one exists."""
    matches: list[tuple[str, Path, Path, dict[str, Any]]] = []
    artifacts_root = root / "dist" / "artifacts"
    for manifest_path in artifacts_root.glob("*/*/build-manifest.json"):
        try:
            manifest = read_json(manifest_path)
            app_name = str(((manifest.get("artifacts") or {}).get("app") or {}).get("path") or "")
            app = manifest_path.parent / app_name
            if not app_name or not app.is_dir():
                continue
            _, validated = local_manifest_for(app)
        except RuntimeError:
            continue
        source = validated.get("source") if isinstance(validated.get("source"), dict) else {}
        source_revision = str(source.get("revision") or "")
        if not revisions_match(revision, source_revision):
            continue
        matches.append(
            (
                str(validated.get("created_at") or ""),
                app,
                manifest_path,
                validated,
            )
        )
    if not matches:
        return None
    _, app, manifest_path, manifest = max(matches, key=lambda item: item[0])
    return app, manifest_path, manifest
