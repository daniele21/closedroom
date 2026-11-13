#!/usr/bin/env python3
"""Guard and restore Vite's tracked frontend output during macOS packaging.

Only call restore after check succeeds at the same HEAD. The build entrypoint
owns that pairing and traps normal success/failure exits. Never mutate unrelated
working-tree paths, local meeting data or finalized dist/artifacts.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


GENERATED_FRONTEND = "src/local_asr_server/static"


def git(root: Path, *args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=capture,
    )


def verify_head(root: Path, expected_head: str) -> None:
    actual = git(root, "rev-parse", "HEAD", capture=True).stdout.strip()
    if actual != expected_head:
        raise RuntimeError("HEAD changed while packaging: refusing generated frontend restoration")


def check_clean(root: Path, expected_head: str) -> None:
    verify_head(root, expected_head)
    changes = git(
        root, "status", "--porcelain", "--untracked-files=all",
        "--", GENERATED_FRONTEND, capture=True,
    ).stdout.strip()
    if changes:
        raise RuntimeError(
            "generated frontend output has preexisting changes; "
            "inspect 'git status --short -- src/local_asr_server/static' "
            "before starting a build (no files modified)"
        )


def restore(root: Path, expected_head: str) -> None:
    verify_head(root, expected_head)
    # This path was clean before Vite ran; only build-owned changes are eligible.
    git(root, "restore", "--source=HEAD", "--staged", "--worktree", "--", GENERATED_FRONTEND)
    git(root, "clean", "-fd", "--", GENERATED_FRONTEND)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "restore"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    try:
        if args.action == "check":
            check_clean(args.root.resolve(), args.expected_head)
        else:
            restore(args.root.resolve(), args.expected_head)
        return 0
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Frontend build hygiene: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
