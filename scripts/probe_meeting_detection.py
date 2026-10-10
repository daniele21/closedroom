#!/usr/bin/env python3
"""Content-free target-Mac probe for opt-in meeting detection feasibility.

Use with Zoom/Teams microphone off -> on -> off. The script neither requests
microphone access nor captures media. JSON evidence contains counters, not
meeting titles, process IDs, application windows, audio or private paths.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_asr_server.meeting_detection import CoreAudioInputObserver, SUPPORTED_APPS


def probe(seconds: float, sample_seconds: float, observer=None, clock=time.monotonic,
          sleeper=time.sleep) -> dict:
    if seconds <= 0 or sample_seconds <= 0:
        raise ValueError("seconds and sample interval must be positive")
    scanner = observer or CoreAudioInputObserver()
    deadline = clock() + seconds
    total = 0
    counts = Counter()
    observed = set()
    transitions = Counter()
    previous: frozenset[str] = frozenset()
    while clock() < deadline:
        sample = scanner.scan()
        total += 1
        counts[sample.capability] += 1
        for app_id in sample.active_bundle_ids:
            if app_id in SUPPORTED_APPS:
                observed.add(app_id)
        for app_id in sample.active_bundle_ids - previous:
            if app_id in SUPPORTED_APPS:
                transitions[f"{app_id}:on"] += 1
        if sample.capability == "supported":
            for app_id in previous - sample.active_bundle_ids:
                transitions[f"{app_id}:off"] += 1
            previous = sample.active_bundle_ids
        sleeper(min(sample_seconds, max(0, deadline - clock())))
    return {
        "schema_version": 1,
        "platform": platform.system(),
        "macos_version": platform.mac_ver()[0],
        "sample_count": total,
        "capability_counts": dict(counts),
        "observed_supported_apps": [SUPPORTED_APPS[app_id] for app_id in sorted(observed)],
        "transition_counts": {
            f"{SUPPORTED_APPS[app_id]}:{kind}": transitions[f"{app_id}:{kind}"]
            for app_id in sorted(SUPPORTED_APPS) for kind in ("on", "off")
            if transitions[f"{app_id}:{kind}"]
        },
        "captures_media": False,
        "uploads_data": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--sample-seconds", type=float, default=1)
    parser.add_argument("--expect-app", choices=("Zoom", "Microsoft Teams"))
    parser.add_argument("--require-on-off", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional local content-free JSON evidence path")
    args = parser.parse_args()
    result = probe(args.seconds, args.sample_seconds)
    result["result"] = "PASS"
    if not result["capability_counts"].get("supported"):
        result["result"] = "INCONCLUSIVE"
    if args.expect_app and args.expect_app not in result["observed_supported_apps"]:
        result["result"] = "FAIL"
    if args.require_on_off and args.expect_app:
        transitions = result["transition_counts"]
        if not (transitions.get(f"{args.expect_app}:on") and transitions.get(f"{args.expect_app}:off")):
            result["result"] = "FAIL"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
