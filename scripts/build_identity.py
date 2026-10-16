#!/usr/bin/env python3
"""Canonical local build identity and monotonic macOS bundle build number.

VERSION remains the public X.Y.Z product identity. CFBundleVersion is a separate,
host-local monotonically increasing integer (including failed build attempts).
The state lives outside dist/, .git and the installed app, so --clean and app
replacement cannot roll the counter back.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import tempfile
from pathlib import Path

MAX_BUILD_NUMBER = 2_147_483_647
VALID_NUMBER = re.compile(r"[1-9][0-9]*\Z")


def app_identity(variant: str, *, environ: dict[str, str] | None = None) -> tuple[str, str, str, str]:
    if variant == "test":
        # Test identity is fixed: arbitrary overrides must never target the
        # stable app's path or LaunchServices/TCC identity by mistake.
        return ("ClosedRoom", "ClosedRoom Test.app", "ClosedRoom Test", "com.closedroom.app.test")
    if variant != "stable":
        raise ValueError(f"Unsupported build variant: {variant}")
    env = environ if environ is not None else os.environ
    name = env.get("CLOSEDROOM_APP_NAME") or "ClosedRoom"
    bundle_name = env.get("CLOSEDROOM_APP_BUNDLE_NAME") or f"{name}.app"
    display_name = env.get("CLOSEDROOM_APP_DISPLAY_NAME") or name
    bundle_id = env.get("CLOSEDROOM_APP_BUNDLE_ID") or "com.closedroom.app"
    if "\t" in "".join((name, bundle_name, display_name, bundle_id)):
        raise ValueError("Build identity must not contain tab characters")
    return (name, bundle_name, display_name, bundle_id)


def validate_number(value: str) -> int:
    if not VALID_NUMBER.fullmatch(value.strip()):
        raise ValueError("Build number must be a positive decimal integer")
    result = int(value.strip())
    if result > MAX_BUILD_NUMBER:
        raise ValueError("Build number exceeds the supported bundle version range")
    return result


def state_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "ClosedRoom" / "Builds" / "build-number.txt"


def next_number(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if path.exists():
            current = validate_number(path.read_text(encoding="utf-8"))
        else:
            current = 0
        if current >= MAX_BUILD_NUMBER:
            raise ValueError("Maximum build number reached")
        number = current + 1
        # Atomic replace, with a separate lock file to serialize processes.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".build-number-", delete=False,
        ) as temp:
            tmp_path = Path(temp.name)
            temp.write(f"{number}\n")
            temp.flush()
            os.fsync(temp.fileno())
        try:
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)
        return number


def main() -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--identity-tsv", action="store_true")
    actions.add_argument("--next-build-number", action="store_true")
    actions.add_argument("--validate-build-number")
    parser.add_argument("--variant", choices=("stable", "test"), default="stable")
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    if args.identity_tsv:
        print("\t".join(app_identity(args.variant)))
    elif args.next_build_number:
        print(next_number(args.state_file or state_path()))
    else:
        print(validate_number(args.validate_build_number))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
