#!/usr/bin/env python3
"""Run one canonical target-Mac evidence owner against a local ad-hoc artifact.

The adapter patches only the artifact-qualification function in-process. The
physical evidence implementation remains owned by the existing release runners.
Production execution never imports this adapter, so release qualification stays
fail-closed on Developer ID + notarization evidence.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import local_real_environment_policy as local_policy
import measured_release_target_mac as measured

TARGETS = {
    "measured_release": "measured_release_target_mac",
    "record_while_ai_busy": "record_while_ai_busy_target_mac",
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        allowed = ", ".join(sorted(TARGETS))
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <{allowed}> [runner args...]")

    target_name = sys.argv[1]
    forwarded = sys.argv[2:]

    # Explicit local-only substitution. The release scripts remain unchanged and
    # still require Developer ID/notarization when invoked normally.
    measured.production_manifest_for = local_policy.local_manifest_for

    target = importlib.import_module(TARGETS[target_name])
    sys.argv = [f"{TARGETS[target_name]}.py", *forwarded]
    result = target.main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
