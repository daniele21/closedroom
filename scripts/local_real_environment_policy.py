#!/usr/bin/env python3
"""Local-only artifact qualification for ClosedRoom REAL_ENVIRONMENT evidence.

This module deliberately does not alter the production release policy. It is
used only by the explicit local REAL_ENVIRONMENT adapter when Apple distribution
authority is unavailable. Accepted artifacts must be exact-revision, finalized,
clean, local Apple-Silicon builds using ad-hoc signing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read local build manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid local build manifest: {path}")
    return payload


def local_manifest_for(app: Path) -> tuple[Path, dict[str, Any]]:
    """Validate one finalized ad-hoc artifact for local physical evidence only."""
    manifest_path = app.parent / "build-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("local app is missing build-manifest.json")

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
    if signing != "ad-hoc":
        raise RuntimeError(
            "local REAL_ENVIRONMENT requires an ad-hoc artifact; "
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
