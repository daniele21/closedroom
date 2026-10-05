#!/usr/bin/env python3
"""Focused functional/performance gate for ClosedRoom capture core."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


DETERMINISTIC_TEST_PATTERNS = [
    "test_native_capture.py",
    "test_screenshot_capture_core.py",
    "test_recording_api.py",
    "test_frontend_call_screenshot_evidence.py",
]


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> int:
    prefix = f"[{cwd}] " if cwd is not None else ""
    print(prefix + "$ " + " ".join(command), flush=True)
    return subprocess.run(command, check=False, env=env, cwd=cwd).returncode


def pnpm_command(*args: str) -> list[str]:
    corepack = shutil.which("corepack")
    if corepack is not None:
        return [corepack, "pnpm", *args]
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError(
            "pnpm (or corepack) is required for capture-core frontend validation."
        )
    return [pnpm, *args]


def uv_python_command(*args: str) -> list[str]:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError(
            "uv is required for capture-core validation; "
            "ClosedRoom supports Python >=3.10,<3.14 and must not inherit an arbitrary global Python."
        )
    return [uv, "run", "python", *args]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--shots", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--enforce-slo", action="store_true")
    args = parser.parse_args()

    env = {**os.environ, "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", ".cache/uv")}

    for pattern in DETERMINISTIC_TEST_PATTERNS:
        status = run(
            uv_python_command(
                "-m",
                "unittest",
                "discover",
                "-s",
                "test",
                "-p",
                pattern,
                "-v",
            ),
            env=env,
        )
        if status != 0:
            return status

    frontend_dir = Path("frontend")
    for frontend_command in (("lint",), ("build",)):
        status = run(
            pnpm_command(*frontend_command),
            env=env,
            cwd=frontend_dir,
        )
        if status != 0:
            return status

    if not args.real:
        return 0

    benchmark = uv_python_command(
        "scripts/benchmark_screenshot_capture_core.py",
        "--shots",
        str(args.shots),
        "--interval",
        str(args.interval),
    )
    if args.enforce_slo:
        benchmark.append("--enforce-slo")
    return run(benchmark, env=env)


if __name__ == "__main__":
    raise SystemExit(main())