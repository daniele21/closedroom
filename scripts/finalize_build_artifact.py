#!/usr/bin/env python3
"""Finalize one successful ClosedRoom build into immutable lineage metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = "build-manifest.json"
CHANGELOG_NAME = "BUILD_CHANGELOG.md"
CHECKSUMS_NAME = "SHA256SUMS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--dmg")
    parser.add_argument("--product", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--dirty", choices=("true", "false"), required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--signing", required=True)
    parser.add_argument("--channel", default="local")
    parser.add_argument("--variant", default="app")
    parser.add_argument("--keep", type=int, default=2)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_tree(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    total_bytes = 0
    file_count = 0
    for candidate in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(path).as_posix()
        if candidate.is_symlink():
            payload = f"LINK->{os.readlink(candidate)}".encode()
            digest.update(relative.encode() + b"\0" + hashlib.sha256(payload).digest())
            file_count += 1
            continue
        if not candidate.is_file():
            continue
        file_digest = bytes.fromhex(sha256_file(candidate))
        digest.update(relative.encode() + b"\0" + file_digest)
        total_bytes += candidate.stat().st_size
        file_count += 1
    return {
        "sha256": digest.hexdigest(),
        "bytes": total_bytes,
        "file_count": file_count,
    }


def file_fingerprint(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() else None


def command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else None


def load_previous(lineage_root: Path, current_dir: Path) -> dict[str, Any] | None:
    candidates: list[tuple[str, dict[str, Any]]] = []
    if not lineage_root.is_dir():
        return None
    for manifest_path in lineage_root.glob(f"*/{MANIFEST_NAME}"):
        if manifest_path.parent == current_dir:
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") != "successful":
            continue
        candidates.append((str(data.get("created_at") or ""), data))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def changed_map(previous: dict[str, Any] | None, current: dict[str, Any], key: str) -> list[str]:
    if previous is None:
        return ["initial comparable build"]
    before = previous.get(key) or {}
    after = current.get(key) or {}
    keys = sorted(set(before) | set(after))
    changes = [f"`{name}`: `{before.get(name)}` → `{after.get(name)}`" for name in keys if before.get(name) != after.get(name)]
    return changes or ["no change"]


def render_delta(previous: dict[str, Any] | None, current: dict[str, Any]) -> str:
    previous_id = previous.get("build_id") if previous else None
    lines = [
        "# Build changelog",
        "",
        f"Build: `{current['build_id']}`",
        f"Source: `{current['source']['revision']}` (dirty: `{str(current['source']['dirty']).lower()}`)",
        f"Previous comparable build: `{previous_id or 'none'}`",
        "",
        "## Source",
        "",
    ]
    if previous:
        lines.append(f"- revision: `{previous['source'].get('revision')}` → `{current['source']['revision']}`")
        lines.append(f"- dirty: `{previous['source'].get('dirty')}` → `{current['source']['dirty']}`")
    else:
        lines.append("- initial comparable build")

    for title, key in (
        ("Dependencies", "dependencies"),
        ("Toolchain", "toolchain"),
        ("Configuration", "configuration"),
    ):
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {item}" for item in changed_map(previous, current, key))

    lines.extend(["", "## Compatibility / migrations", "", "- no automatic compatibility migration inferred by the build finalizer; code/schema migrations remain owned by their feature contracts"])
    lines.extend(["", "## Artifact metrics", ""])
    app_metrics = current["artifacts"]["app"]
    lines.append(f"- app bytes: `{app_metrics['bytes']}`")
    lines.append(f"- app files: `{app_metrics['file_count']}`")
    lines.append(f"- app aggregate SHA-256: `{app_metrics['sha256']}`")
    if previous and previous.get("artifacts", {}).get("app"):
        old_bytes = int(previous["artifacts"]["app"].get("bytes") or 0)
        lines.append(f"- app size delta bytes: `{app_metrics['bytes'] - old_bytes:+d}`")
    if current["artifacts"].get("dmg"):
        lines.append(f"- dmg bytes: `{current['artifacts']['dmg']['bytes']}`")
        lines.append(f"- dmg SHA-256: `{current['artifacts']['dmg']['sha256']}`")

    lines.extend(["", "## Validation", "", "- build: `PASS`", "- code-sign verification: `PASS`", "- packaged-app smoke: recorded separately by the canonical smoke command / preflight job", ""])
    return "\n".join(lines)


def enforce_retention(lineage_root: Path, current_dir: Path, keep: int) -> list[str]:
    if keep < 1:
        raise ValueError("keep must be >= 1")
    successful: list[tuple[str, Path]] = []
    for manifest_path in lineage_root.glob(f"*/{MANIFEST_NAME}"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "successful":
            successful.append((str(data.get("created_at") or ""), manifest_path.parent))
    successful.sort(reverse=True)
    removed: list[str] = []
    for _, path in successful[keep:]:
        if path == current_dir:
            continue
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def read_bundle_identity(app: Path, product_version: str, bundle_id: str) -> int:
    """Validate signed-bundle metadata before making an immutable manifest."""
    with (app / "Contents" / "Info.plist").open("rb") as handle:
        bundle_info = plistlib.load(handle)
    if str(bundle_info.get("CFBundleShortVersionString", "")) != product_version:
        raise ValueError("bundle product version does not match canonical VERSION")
    if str(bundle_info.get("CFBundleIdentifier", "")) != bundle_id:
        raise ValueError("bundle identifier does not match requested build variant")
    number = str(bundle_info.get("CFBundleVersion", ""))
    if not number.isdecimal() or int(number) < 1:
        raise ValueError("bundle must have a positive numeric CFBundleVersion")
    return int(number)


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    app_path = Path(args.app).resolve()
    dmg_path = Path(args.dmg).resolve() if args.dmg else None
    artifact_dir.mkdir(parents=True, exist_ok=True)

    bundle_build_number = read_bundle_identity(app_path, args.version, args.bundle_id)

    manifest_path = artifact_dir / MANIFEST_NAME
    if manifest_path.exists():
        raise SystemExit(f"refusing to mutate finalized artifact: {manifest_path}")
    if not app_path.is_dir():
        raise SystemExit(f"app bundle not found: {app_path}")
    if dmg_path and not dmg_path.is_file():
        raise SystemExit(f"DMG not found: {dmg_path}")

    lineage_root = artifact_dir.parent
    previous = load_previous(lineage_root, artifact_dir)
    app_metrics = fingerprint_tree(app_path)
    dmg_metrics = None
    if dmg_path:
        dmg_metrics = {
            "path": dmg_path.name,
            "sha256": sha256_file(dmg_path),
            "bytes": dmg_path.stat().st_size,
        }

    created_at = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "successful",
        "created_at": created_at,
        "project": "local-asr-server",
        "product": args.product,
        "product_version": args.version,
        "bundle_build_number": bundle_build_number,
        "build_id": args.build_id,
        "previous_successful_build_id": previous.get("build_id") if previous else None,
        "lineage": {
            "project": "local-asr-server",
            "platform": "macos",
            "architecture": platform.machine() or "arm64",
            "channel": args.channel,
            "variant": args.variant,
        },
        "source": {
            "revision": args.source_revision,
            "dirty": args.dirty == "true",
        },
        "dependencies": {
            "pyproject_sha256": file_fingerprint(root / "pyproject.toml"),
            "uv_lock_sha256": file_fingerprint(root / "uv.lock"),
            "frontend_lock_sha256": file_fingerprint(root / "frontend" / "pnpm-lock.yaml"),
        },
        "toolchain": {
            "python": platform.python_version(),
            "macos": platform.mac_ver()[0] or None,
            "machine": platform.machine() or None,
            "swift": command_version(["swiftc", "--version"]),
            "uv": command_version(["uv", "--version"]),
            "pnpm": command_version(["pnpm", "--version"]),
        },
        "configuration": {
            "bundle_id": args.bundle_id,
            "signing": args.signing,
        },
        "artifacts": {
            "app": {
                "path": app_path.name,
                **app_metrics,
            },
            "dmg": dmg_metrics,
        },
        "validation": {
            "build": "pass",
            "codesign": "pass",
            "packaged_app_smoke": "separate-evidence",
        },
    }

    changelog = render_delta(previous, manifest)
    (artifact_dir / CHANGELOG_NAME).write_text(changelog, encoding="utf-8")

    checksum_lines = [f"{app_metrics['sha256']}  {app_path.name}/"]
    if dmg_metrics:
        checksum_lines.append(f"{dmg_metrics['sha256']}  {dmg_path.name}")
    (artifact_dir / CHECKSUMS_NAME).write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    removed = enforce_retention(lineage_root, artifact_dir, args.keep)
    print(json.dumps({"manifest": str(manifest_path), "removed_builds": removed}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
