#!/usr/bin/env python3
"""Resolve and validate the canonical ClosedRoom product version.

`VERSION` is the sole product-version data owner. The legacy Python package
version in pyproject.toml is an implementation-package identity and is not used
for the macOS app, artifact or GitHub Release identity.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


VERSION_FILE = "VERSION"
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def validate_version(value: str) -> str:
    version = value.strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError(
            "ClosedRoom product version must be numeric SemVer X.Y.Z without "
            f"prerelease/build metadata; got {value!r}"
        )
    return version


def read_product_version(root: Path) -> str:
    path = root / VERSION_FILE
    try:
        value = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"canonical product version missing: {path}") from exc
    return validate_version(value)


def tag_for_version(version: str) -> str:
    return f"v{validate_version(version)}"


def version_from_tag(tag: str) -> str:
    value = tag.strip()
    if not value.startswith("v"):
        raise ValueError(f"ClosedRoom release tag must use vX.Y.Z; got {tag!r}")
    return validate_version(value[1:])


def assert_tag_matches_product(root: Path, tag: str) -> str:
    version = read_product_version(root)
    tagged = version_from_tag(tag)
    if tagged != version:
        raise ValueError(
            f"release tag {tag!r} does not match canonical product version {version!r}"
        )
    return version


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--expect-tag",
        help="Fail unless this vX.Y.Z tag matches the canonical product version",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    try:
        version = (
            assert_tag_matches_product(root, args.expect_tag)
            if args.expect_tag
            else read_product_version(root)
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
