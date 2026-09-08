#!/usr/bin/env python3
"""Build, Developer-ID sign, notarize and finalize a ClosedRoom release artifact.

This command is intentionally separate from the ad-hoc/CI artifact builder.
It requires protected Apple authority and performs every mutation before the
immutable build manifest is written.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import secrets
import shutil
import subprocess
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--signing-identity", default=os.getenv("CLOSEDROOM_SIGN_IDENTITY", ""))
    parser.add_argument("--notary-keychain-profile", default=os.getenv("CLOSEDROOM_NOTARY_KEYCHAIN_PROFILE", ""))
    parser.add_argument("--build-id", default=os.getenv("CLOSEDROOM_BUILD_ID", ""))
    parser.add_argument("--keep", type=int, default=int(os.getenv("CLOSEDROOM_LOCAL_ARTIFACT_KEEP", "2")))
    return parser.parse_args()


def developer_id_identity(identity: str) -> bool:
    return identity.strip().startswith("Developer ID Application:")


def codesign_details(app: Path, *, cwd: Path) -> str:
    completed = subprocess.run(
        ["/usr/bin/codesign", "-dv", "--verbose=4", str(app)],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)


def codesign_is_release_ready(details: str) -> bool:
    return "Authority=Developer ID Application:" in details and bool(re.search(r"^Timestamp=.+$", details, re.MULTILINE))


def write_codesign_wrapper(directory: Path) -> Path:
    wrapper = directory / "codesign"
    wrapper.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "args=()\n"
        "for arg in \"$@\"; do\n"
        "  if [[ \"$arg\" == \"--timestamp=none\" ]]; then args+=(\"--timestamp\"); else args+=(\"$arg\"); fi\n"
        "done\n"
        "exec /usr/bin/codesign \"${args[@]}\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def notary_submit(dmg: Path, profile: str, *, cwd: Path) -> dict[str, Any]:
    completed = run(
        [
            "xcrun", "notarytool", "submit", str(dmg),
            "--keychain-profile", profile,
            "--wait", "--output-format", "json",
        ],
        cwd=cwd,
        timeout=1800,
    )
    payload = json.loads(completed.stdout or "{}")
    if str(payload.get("status") or "").lower() != "accepted":
        raise RuntimeError(f"notarization was not accepted: {payload.get('status') or 'unknown'}")
    return payload


def git_clean(root: Path) -> bool:
    return run(["git", "status", "--porcelain"], cwd=root).stdout.strip() == ""


def source_revision(root: Path) -> str:
    return run(["git", "rev-parse", "--short=12", "HEAD"], cwd=root).stdout.strip()


def app_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def bundle_identity(app: Path) -> tuple[str, str]:
    with (app / "Contents" / "Info.plist").open("rb") as handle:
        payload = plistlib.load(handle)
    return str(payload.get("CFBundleIdentifier") or ""), str(payload.get("CFBundleExecutable") or "")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    identity = str(args.signing_identity or "").strip()
    profile = str(args.notary_keychain_profile or "").strip()

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("production artifact build requires a target Apple-Silicon Mac")
    if not developer_id_identity(identity):
        raise SystemExit("CLOSEDROOM_SIGN_IDENTITY must be a Developer ID Application identity")
    if not profile:
        raise SystemExit("CLOSEDROOM_NOTARY_KEYCHAIN_PROFILE is required")
    if args.keep < 1:
        raise SystemExit("--keep must be >= 1")
    if not git_clean(root):
        raise SystemExit("production artifact build requires a clean checkout")
    for command in ("uv", "pnpm", "ffmpeg", "xcrun"):
        if shutil.which(command) is None:
            raise SystemExit(f"required command not found: {command}")

    version = app_version(root)
    revision = source_revision(root)
    build_id = str(args.build_id or "").strip() or f"release-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    build_id = re.sub(r"[^A-Za-z0-9._-]+", "-", build_id)
    app_name = os.getenv("CLOSEDROOM_APP_NAME", "ClosedRoom")
    staging_app = root / "dist" / f"{app_name}-{version}.app"
    staging_dmg = root / "dist" / f"{app_name}-{version}.dmg"
    artifact_dir = root / "dist" / "artifacts" / "macos-arm64-release-package" / build_id
    final_basename = f"{app_name}-{version}-{build_id}-{revision}"
    final_app = artifact_dir / f"{final_basename}.app"
    final_dmg = artifact_dir / f"{final_basename}.dmg"

    if artifact_dir.exists():
        raise SystemExit(f"artifact build id already exists: {artifact_dir}")

    started_at = datetime.now(timezone.utc).isoformat()
    notary_payload: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="closedroom-release-codesign-") as tmp:
            wrapper_dir = Path(tmp)
            write_codesign_wrapper(wrapper_dir)
            env = os.environ.copy()
            env["PATH"] = f"{wrapper_dir}:{env.get('PATH', '')}"
            env["CLOSEDROOM_SIGN_IDENTITY"] = identity
            env["CLOSEDROOM_BUILD_CHANNEL"] = "release"
            run(["bash", "build.sh", "--no-dmg", "--clean"], cwd=root, env=env, timeout=3600)

        if not staging_app.is_dir():
            raise RuntimeError(f"build did not produce {staging_app}")
        run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(staging_app)], cwd=root)
        details = codesign_details(staging_app, cwd=root)
        if not codesign_is_release_ready(details):
            raise RuntimeError("app is not Developer-ID signed with a secure timestamp")

        bundle_id, executable = bundle_identity(staging_app)
        if not bundle_id or not executable:
            raise RuntimeError("built app is missing bundle identity")

        run(["bash", "create_dmg.sh", str(staging_app), str(staging_dmg), app_name, version], cwd=root, timeout=600)
        if not staging_dmg.is_file():
            raise RuntimeError("DMG creation did not produce an artifact")

        notary_payload = notary_submit(staging_dmg, profile, cwd=root)
        run(["xcrun", "stapler", "staple", str(staging_dmg)], cwd=root, timeout=300)
        run(["xcrun", "stapler", "validate", str(staging_dmg)], cwd=root, timeout=120)
        run(["spctl", "--assess", "--type", "open", "--context", "context:primary-signature", "--verbose=2", str(staging_dmg)], cwd=root, timeout=120)

        artifact_dir.mkdir(parents=True)
        shutil.move(str(staging_app), str(final_app))
        shutil.move(str(staging_dmg), str(final_dmg))

        release_evidence = {
            "schema_version": 1,
            "status": "pass",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "source_revision": revision,
            "build_id": build_id,
            "bundle_id": bundle_id,
            "signing": "developer-id",
            "secure_timestamp": True,
            "notarization": "accepted",
            "notary_submission_id": str(notary_payload.get("id") or "") or None,
            "notary_profile_configured": True,
            "stapler_validation": "pass",
            "gatekeeper_assessment": "pass",
        }
        (artifact_dir / "production-release-evidence.json").write_text(
            json.dumps(release_evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        run(
            [
                "python3", "scripts/finalize_build_artifact.py",
                "--root", str(root),
                "--artifact-dir", str(artifact_dir),
                "--app", str(final_app),
                "--dmg", str(final_dmg),
                "--product", app_name,
                "--version", version,
                "--build-id", build_id,
                "--source-revision", revision,
                "--dirty", "false",
                "--bundle-id", bundle_id,
                "--signing", "developer-id-notarized",
                "--channel", "release",
                "--variant", "package",
                "--keep", str(args.keep),
            ],
            cwd=root,
        )
    except Exception:
        shutil.rmtree(artifact_dir, ignore_errors=True)
        raise

    print(json.dumps({"status": "pass", "artifact_dir": str(artifact_dir), "app": str(final_app), "dmg": str(final_dmg)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
