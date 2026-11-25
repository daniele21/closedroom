#!/usr/bin/env python3
"""Explicit GUI-Terminal smoke for the exact finalized ClosedRoom.app.

Does not install/restart/overwrite /Applications/ClosedRoom.app. No recording,
Google account, sync credentials or external transport. Only synthetic Keychain
entries from the signed bundle binary, removed within that same diagnostic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

import local_real_environment_policy as artifact_policy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--app", help="Explicit exact-HEAD finalized .app; never use a random installed copy")
    parser.add_argument("--build", action="store_true", help="Build a separate identified local-development artifact (not install)")
    parser.add_argument("--backend", choices=("data-protection", "local-development"), default="data-protection")
    parser.add_argument("--sign-identity", help="Explicit 40-hex SHA-1 fingerprint of local code-signing certificate")
    return parser.parse_args()


def validate_artifact(root: Path, app: Path, revision: str) -> tuple[Path, str]:
    _, manifest = artifact_policy.local_manifest_for(app, allow_identified=True)
    source = manifest.get("source") or {}
    if not artifact_policy.revisions_match(revision, str(source.get("revision") or "")):
        raise RuntimeError("App artifact does not match the exact source revision")
    signing = (manifest.get("configuration") or {}).get("signing")
    if signing not in ("identified", "ad-hoc"):
        raise RuntimeError("Unsupported app signing identity")
    with (app / "Contents" / "Info.plist").open("rb") as file:
        info = plistlib.load(file)
    if info.get("CFBundleIdentifier") != "com.closedroom.app":
        raise RuntimeError("Unexpected app bundle identifier")
    executable_name = info.get("CFBundleExecutable")
    if not isinstance(executable_name, str) or "/" in executable_name:
        raise RuntimeError("Invalid bundle executable")
    exe = app / "Contents" / "MacOS" / executable_name
    if not exe.is_file():
        raise RuntimeError("Frozen executable missing")
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app)],
        check=True, capture_output=True, timeout=120,
    )
    return exe, signing


def validate_signing_identity(fingerprint: str, app: Path | None = None) -> None:
    """Verify selected local identity, and the actual signed leaf if given."""
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9A-Fa-f]{40}", fingerprint):
        raise RuntimeError("Specify an exact 40-hex --sign-identity certificate fingerprint")
    fingerprint = fingerprint.upper()
    if app is None:
        found = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        identities = re.findall(r"(?m)^\s*\d+\)\s+([0-9A-Fa-f]{40})\s", found.stdout)
        if fingerprint not in [value.upper() for value in identities]:
            raise RuntimeError("Selected signing identity is unavailable; no build attempted")
        return
    # Export ONLY the public certificate chain to a disposable directory.
    # Do not infer certificate identity merely from the build manifest.
    with tempfile.TemporaryDirectory(prefix="closedroom-signature-check-") as tmp:
        prefix = str(Path(tmp) / "cert")
        subprocess.run(
            ["codesign", "-d", "--extract-certificates", prefix, str(app)],
            capture_output=True, check=True, timeout=30,
        )
        leaf = Path(prefix + "0")
        if not leaf.is_file() or hashlib.sha1(leaf.read_bytes()).hexdigest().upper() != fingerprint:
            raise RuntimeError("Actual bundle signing certificate does not match selected identity")


def main() -> int:
    args = parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Only real macOS Apple Silicon can qualify the packaged Keychain")
    root = Path(args.root).expanduser().resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root,
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    local = args.backend == "local-development"
    if local:
        validate_signing_identity(args.sign_identity)
    elif args.build:
        raise RuntimeError("Data Protection Keychain build blocked: use an explicitly provisioned --app; no ad-hoc retry")
    elif args.sign_identity:
        raise RuntimeError("--sign-identity is only for explicit local-development diagnostics")
    built_app = None
    if args.build:
        if args.app:
            raise RuntimeError("--app and --build are mutually exclusive")
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root,
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout
        if dirty.strip():
            raise RuntimeError("Checkout is not clean; refusing to build a dirty candidate")
        env = os.environ.copy()
        env["CLOSEDROOM_SIGN_IDENTITY"] = args.sign_identity.upper()
        env["CLOSEDROOM_BUILD_CHANNEL"] = "local-keychain-development"
        env["CLOSEDROOM_BUILD_ID"] = "keychain-" + secrets.token_hex(12)
        env["CLOSEDROOM_SOURCE_REVISION"] = revision
        # Separate artifact lineage, avoids pruning other qualification builds.
        artifact_dir = root / "dist" / "artifacts" / "macos-arm64-local-keychain-development-app" / env["CLOSEDROOM_BUILD_ID"]
        # Creates an immutable finalized artifact. Never --install.
        subprocess.run(
            ["bash", "scripts/build_artifact.sh", "--no-dmg"],
            cwd=root, env=env, check=True, timeout=3600,
        )
        manifest = artifact_policy.read_json(artifact_dir / "build-manifest.json")
        app_name = ((manifest.get("artifacts") or {}).get("app") or {}).get("path")
        if not isinstance(app_name, str) or Path(app_name).name != app_name or not app_name.endswith(".app"):
            raise RuntimeError("Identified build did not finalize an app")
        built_app = artifact_dir / app_name
    if args.app:
        app = Path(args.app).expanduser().resolve()
    elif built_app is not None:
        app = built_app
    else:
        raise RuntimeError("Specify --app with an exact finalized candidate, or --backend local-development --build")
    executable, signing = validate_artifact(root, app, revision)
    if signing != "identified":
        raise RuntimeError("Identified signature required; ad-hoc is not qualifying evidence")
    if local:
        validate_signing_identity(args.sign_identity, app)
    proc = subprocess.run(
        [str(executable), "secure-sync-keychain-smoke"],
        capture_output=True, text=True, timeout=45,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "Signed bundle Keychain diagnostic failed. "
            "Use a logged-in GUI Terminal; the background CI Keychain is not interactive."
        )
    try:
        answer = json.loads(proc.stdout.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Bundled Keychain diagnostic did not return a valid result") from exc
    expected = {
        "schema": "closedroom.packaged-keychain-smoke/v1",
        "status": "pass",
        "frozen_app_process": True,
        "independent_child": True,
        "synthetic_only": True,
        "cleanup": True,
    }
    if answer != expected:
        raise RuntimeError("Invalid bundle Keychain evidence")
    # The second command exercises the new experimental native provider:
    # create, atomic item update, zero-length preparation, signed-binary
    # child read and cleanup. Still only synthetic identifiers and secrets.
    vault_proc = subprocess.run(
        [str(executable), "secure-sync-local-vault-smoke" if local else "secure-sync-native-vault-smoke"],
        capture_output=True, text=True, timeout=45,
    )
    if vault_proc.returncode != 0:
        # Never emit raw child stdout/stderr: secrets, paths or OS details
        # may appear in unexpected tracebacks. Only allowlist an operation
        # and a bounded OSStatus from the native Keychain exception.
        matches = re.findall(
            r"Keychain (creation|read|update|cleanup|interaction policy) failed "
            r"\(OSStatus (-?\d{1,7})\)",
            vault_proc.stderr[-20000:],
        )
        operation, status = matches[-1] if matches else ("unknown", "unavailable")
        raise RuntimeError(
            "Packaged native-vault Keychain diagnostic failed: "
            f"phase={operation}, osstatus={status}, "
            f"returncode={vault_proc.returncode}. "
            "No fallback or permission change was attempted."
        )
    try:
        vault_answer = json.loads(vault_proc.stdout.strip())
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("Native-vault diagnostic returned invalid evidence") from exc
    if vault_answer != {
        "schema": ("closedroom.local-development-vault-probe/v1" if local else "closedroom.native-vault-probe/v1"),
        "status": "pass",
        "independent_child": True,
        "updated_item": True,
        "empty_preparation": True,
        "cleanup": True,
        "synthetic_only": True,
    }:
        raise RuntimeError("Native-vault diagnostic evidence mismatched")
    print(json.dumps({
        "status": "pass",
        "source_revision": revision,
        "signing": signing,
        "bundle_id": "com.closedroom.app",
        "scope": "packaged-GUI-Terminal-Keychain-only",
        "independent_child": True,
        "cleanup": True,
        "installed_app_modified": False,
        "native_vault_probe": True,
        "backend": args.backend,
        "data_protection_probe_pass": not local,
        "cross_build_acl_verified": False,
        "updated_item": True,
        "empty_preparation": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
