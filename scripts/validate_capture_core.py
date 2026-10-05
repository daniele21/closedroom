#!/usr/bin/env python3
"""Focused functional/performance gate for ClosedRoom capture core."""
from __future__ import annotations

import argparse
import subprocess
import sys


DETERMINISTIC_TESTS = [
    "test.test_native_capture",
    "test.test_screenshot_capture_core",
    "test.test_recording_api.RecordingApiTests.test_screenshot_api_uses_store_owned_staging_and_is_idempotent",
    "test.test_frontend_call_screenshot_evidence",
]


def run(command: list[str]) -> int:
    print("$ " + " ".join(command), flush=True)
    return subprocess.run(command, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--shots", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--enforce-slo", action="store_true")
    args = parser.parse_args()

    test_command = [
        sys.executable,
        "-m",
        "unittest",
        *DETERMINISTIC_TESTS,
        "-v",
    ]
    status = run(test_command)
    if status != 0 or not args.real:
        return status

    benchmark = [
        sys.executable,
        "scripts/benchmark_screenshot_capture_core.py",
        "--shots",
        str(args.shots),
        "--interval",
        str(args.interval),
    ]
    if args.enforce_slo:
        benchmark.append("--enforce-slo")
    return run(benchmark)


if __name__ == "__main__":
    raise SystemExit(main())