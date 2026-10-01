#!/usr/bin/env python3
"""Validate and stage one immutable ClosedRoom artifact for a GitHub Release.

This is a publication adapter, not a build owner. It reads an already-finalized
production artifact, validates its product/source/distribution evidence, copies
the exact DMG bytes under the public release filename, and emits deterministic
release notes, checksums and an internal release plan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from product_version import assert_tag_matches_product

MANIFEST_NAME = "build-manifest.json"
BUILD_CHANGELOG_NAME = "BUILD_CHANGELOG.md"
INPUT_CHECKSUMS_NAME = "SHA256SUMS"
PRODUCTION_EVIDENCE_NAME = "production-release-evidence.json"
RELEASE_NOTES_NAME = "RELEASE_NOTES.md"
RELEASE_PLAN_NAME = "release-plan.json"
PUBLIC_CHECKSUMS_NAME = "SHA256SUMS"
REQUIRED_NOTE_HEADINGS = (
    "## Highlights",
    "## Compatibility",
    "## Installation",
    "## Privacy",
    "## Known limitations",
)
REQUIRED_PRODUCTION_EVIDENCE: dict[str, Any] = {
    "status": "pass",
    "signing": "developer-id",
    "secure_timestamp": True,
    "app_notarization": "accepted",
    "app_stapler_validation": "pass",
    "app_gatekeeper_assessment": "pass",
    "dmg_notarization": "accepted",
    "dmg_stapler_validation": "pass",
    "dmg_gatekeeper_assessment": "pass",
    "notary_profile_configured": True,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--notes-source", required=True)
    parser.add_argument("--release-state", choices=("stable", "prerelease"), required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"required release metadata missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON release metadata: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"release metadata must be a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def validate_notes(path: Path) -> str:
    try:
        body = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"release notes source missing: {path}") from exc
    if not body:
        raise RuntimeError("release notes source must not be empty")
    missing = [heading for heading in REQUIRED_NOTE_HEADINGS if heading not in body]
    if missing:
        raise RuntimeError(
            "release notes source is missing required sections: " + ", ".join(missing)
        )
    return body


def validate_artifact(
    *,
    root: Path,
    artifact_dir: Path,
    tag: str,
    source_revision: str,
) -> tuple[str, dict[str, Any], Path]:
    version = assert_tag_matches_product(root, tag)
    manifest = read_json(artifact_dir / MANIFEST_NAME)
    evidence = read_json(artifact_dir / PRODUCTION_EVIDENCE_NAME)

    require_equal(manifest.get("status"), "successful", "manifest status")
    require_equal(manifest.get("product"), "ClosedRoom", "manifest product")
    require_equal(manifest.get("product_version"), version, "manifest product version")
    require_equal((manifest.get("source") or {}).get("revision"), source_revision, "manifest source revision")
    require_equal((manifest.get("source") or {}).get("dirty"), False, "manifest dirty state")

    lineage = manifest.get("lineage") or {}
    require_equal(lineage.get("platform"), "macos", "manifest platform")
    require_equal(lineage.get("architecture"), "arm64", "manifest architecture")
    require_equal(lineage.get("channel"), "release", "manifest channel")
    require_equal(lineage.get("variant"), "package", "manifest variant")
    require_equal(
        (manifest.get("configuration") or {}).get("signing"),
        "developer-id-notarized",
        "manifest signing",
    )

    for key, expected in REQUIRED_PRODUCTION_EVIDENCE.items():
        require_equal(evidence.get(key), expected, f"production evidence {key}")
    require_equal(evidence.get("source_revision"), source_revision, "production evidence source revision")
    require_equal(evidence.get("build_id"), manifest.get("build_id"), "production evidence build id")
    require_equal(
        evidence.get("bundle_id"),
        (manifest.get("configuration") or {}).get("bundle_id"),
        "production evidence bundle id",
    )

    dmg_meta = (manifest.get("artifacts") or {}).get("dmg")
    if not isinstance(dmg_meta, dict):
        raise RuntimeError("release manifest is missing DMG metadata")
    dmg_name = str(dmg_meta.get("path") or "").strip()
    expected_sha = str(dmg_meta.get("sha256") or "").strip()
    expected_bytes = dmg_meta.get("bytes")
    if not dmg_name or not expected_sha or not isinstance(expected_bytes, int):
        raise RuntimeError("release manifest has incomplete DMG metadata")
    dmg = artifact_dir / dmg_name
    if not dmg.is_file():
        raise RuntimeError(f"release DMG is missing: {dmg}")
    require_equal(sha256_file(dmg), expected_sha, "DMG SHA-256")
    require_equal(dmg.stat().st_size, expected_bytes, "DMG size")

    changelog = artifact_dir / BUILD_CHANGELOG_NAME
    if not changelog.is_file():
        raise RuntimeError(f"build changelog is missing: {changelog}")
    input_checksums = artifact_dir / INPUT_CHECKSUMS_NAME
    try:
        checksum_text = input_checksums.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"build checksums are missing: {input_checksums}") from exc
    if f"{expected_sha}  {dmg_name}" not in checksum_text:
        raise RuntimeError("build checksums do not contain the manifest DMG SHA-256")

    return version, manifest, dmg


def stage_release(
    *,
    root: Path,
    artifact_dir: Path,
    tag: str,
    source_revision: str,
    notes_source: Path,
    release_state: str,
    output_dir: Path,
) -> dict[str, Any]:
    if release_state not in {"stable", "prerelease"}:
        raise ValueError(f"unsupported release state: {release_state}")
    if output_dir.exists():
        raise RuntimeError(f"refusing to replace existing release staging directory: {output_dir}")

    version, manifest, dmg = validate_artifact(
        root=root,
        artifact_dir=artifact_dir,
        tag=tag,
        source_revision=source_revision,
    )
    notes_body = validate_notes(notes_source)

    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True)
    public_dmg_name = f"ClosedRoom-{tag}-macos-arm64.dmg"
    public_dmg = assets_dir / public_dmg_name
    shutil.copyfile(dmg, public_dmg)
    require_equal(
        sha256_file(public_dmg),
        (manifest.get("artifacts") or {}).get("dmg", {}).get("sha256"),
        "staged DMG SHA-256",
    )

    source_manifest = artifact_dir / MANIFEST_NAME
    source_changelog = artifact_dir / BUILD_CHANGELOG_NAME
    public_manifest = assets_dir / MANIFEST_NAME
    public_changelog = assets_dir / BUILD_CHANGELOG_NAME
    shutil.copyfile(source_manifest, public_manifest)
    shutil.copyfile(source_changelog, public_changelog)

    checksum_targets = (public_dmg, public_manifest, public_changelog)
    checksum_lines = [
        f"{sha256_file(path)}  {path.name}" for path in checksum_targets
    ]
    public_checksums = assets_dir / PUBLIC_CHECKSUMS_NAME
    public_checksums.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    title = f"ClosedRoom {tag}"
    notes = f"# {title}\n\n{notes_body}\n"
    notes_path = output_dir / RELEASE_NOTES_NAME
    notes_path.write_text(notes, encoding="utf-8")

    asset_paths = (public_dmg, public_checksums, public_manifest, public_changelog)
    assets = [
        {
            "name": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in asset_paths
    ]
    plan = {
        "schema_version": 1,
        "tag": tag,
        "title": title,
        "product_version": version,
        "source_revision": source_revision,
        "build_id": manifest.get("build_id"),
        "draft": True,
        "prerelease": release_state == "prerelease",
        "make_latest": release_state == "stable",
        "notes": RELEASE_NOTES_NAME,
        "assets_directory": "assets",
        "assets": assets,
    }
    (output_dir / RELEASE_PLAN_NAME).write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return plan


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    plan = stage_release(
        root=root,
        artifact_dir=Path(args.artifact_dir).resolve(),
        tag=args.tag.strip(),
        source_revision=args.source_revision.strip(),
        notes_source=Path(args.notes_source).resolve(),
        release_state=args.release_state,
        output_dir=Path(args.output_dir).resolve(),
    )
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
