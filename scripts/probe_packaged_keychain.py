#!/usr/bin/env python3
"""Explicit GUI-Terminal smoke for the exact finalized ClosedRoom.app.

Does not install/restart/overwrite /Applications/ClosedRoom.app. No recording,
Google account, sync credentials or external transport. Only synthetic Keychain
entries from the signed bundle binary, removed within that same diagnostic.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import subprocess
from pathlib import Path

import local_real_environment_policy as artifact_policy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--app", help="Explicit exact-HEAD finalized .app; never use a random installed copy")
    parser.add_argument("--build", action="store_true", help="Build a new ad-hoc signed exact-HEAD bundle in dist (not install)")
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


def main() -> int:
    args = parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("Only real macOS Apple Silicon can qualify the packaged Keychain")
    root = Path(args.root).expanduser().resolve()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root,
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
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
        env.pop("CLOSEDROOM_SIGN_IDENTITY", None)
        env["CLOSEDROOM_BUILD_CHANNEL"] = "local-real-environment"
        # Creates an immutable finalized artifact. Never --install.
        subprocess.run(
            ["bash", "scripts/build_artifact.sh", "--no-dmg"],
            cwd=root, env=env, check=True, timeout=3600,
        )
        # Generated frontend cleanup is owned by the existing local suite.
        # This command does not auto-restore/overwrite tracked source files.
    if args.app:
        app = Path(args.app).expanduser().resolve()
    else:
        found = artifact_policy.find_exact_local_app(root, revision)
        if found is None:
            raise RuntimeError("No exact-HEAD finalized app. Rerun with --build.")
        app = found[0]
    executable, signing = validate_artifact(root, app, revision)
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
    print(json.dumps({
        "status": "pass",
        "source_revision": revision,
        "signing": signing,
        "bundle_id": "com.closedroom.app",
        "scope": "packaged-GUI-Terminal-Keychain-only",
        "independent_child": True,
        "cleanup": True,
        "installed_app_modified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
