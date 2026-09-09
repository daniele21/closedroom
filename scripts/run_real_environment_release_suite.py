#!/usr/bin/env python3
"""Run and aggregate ClosedRoom's automated REAL_ENVIRONMENT release evidence.

This is an operator-facing orchestration layer only. The canonical evidence
owners remain measured_release_target_mac.py and record_while_ai_busy_target_mac.py.
The suite runs both against the same exact Developer-ID signed/notarized app and
writes one bounded machine-readable summary without transcript or meeting text.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import measured_release_target_mac as measured


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--app",
        required=True,
        help="Exact Developer-ID signed, notarized and stapled ClosedRoom.app",
    )
    parser.add_argument("--output")
    parser.add_argument("--record-seconds", type=float, default=8.0)
    parser.add_argument("--seed-record-seconds", type=float, default=20.0)
    parser.add_argument("--capture-seconds", type=float, default=6.0)
    parser.add_argument("--sample-interval", type=float, default=0.75)
    parser.add_argument("--job-timeout", type=float, default=900.0)
    parser.add_argument("--active-timeout", type=float, default=120.0)
    parser.add_argument("--benchmark-repeats", type=int, default=3)
    parser.add_argument("--keep-sandbox", action="store_true")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def child_summary(path: Path, returncode: int) -> dict[str, Any]:
    payload = read_json(path)
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    failed_checks = [
        str(item.get("name") or "unknown")
        for item in checks
        if isinstance(item, dict) and item.get("status") == "fail"
    ]
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    status = str(payload.get("status") or "missing")
    return {
        "status": status,
        "returncode": returncode,
        "evidence": str(path),
        "failed_checks": failed_checks,
        "errors": [str(value)[:500] for value in errors],
    }


def child_passed(summary: dict[str, Any]) -> bool:
    return summary.get("returncode") == 0 and summary.get("status") == "pass"


def build_commands(
    root: Path,
    app: Path,
    measured_output: Path,
    contention_output: Path,
    args: argparse.Namespace,
) -> list[tuple[str, list[str], Path, float]]:
    common = ["--root", str(root), "--app", str(app)]
    measured_command = [
        sys.executable,
        "scripts/measured_release_target_mac.py",
        *common,
        "--record-seconds",
        str(args.record_seconds),
        "--sample-interval",
        str(args.sample_interval),
        "--job-timeout",
        str(args.job_timeout),
        "--benchmark-repeats",
        str(args.benchmark_repeats),
        "--output",
        str(measured_output),
    ]
    contention_command = [
        sys.executable,
        "scripts/record_while_ai_busy_target_mac.py",
        *common,
        "--seed-record-seconds",
        str(args.seed_record_seconds),
        "--capture-seconds",
        str(args.capture_seconds),
        "--active-timeout",
        str(args.active_timeout),
        "--job-timeout",
        str(args.job_timeout),
        "--sample-interval",
        str(args.sample_interval),
        "--output",
        str(contention_output),
    ]
    if args.keep_sandbox:
        measured_command.append("--keep-sandbox")
        contention_command.append("--keep-sandbox")
    return [
        ("measured_release", measured_command, measured_output, 5400.0),
        ("record_while_ai_busy", contention_command, contention_output, 3600.0),
    ]


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def print_summary(report: dict[str, Any], output: Path) -> None:
    print("\nClosedRoom REAL_ENVIRONMENT release suite")
    print(f"candidate: {report.get('source_revision') or 'unknown'}")
    for name in ("measured_release", "record_while_ai_busy"):
        child = (report.get("tests") or {}).get(name) or {}
        label = name.replace("_", " ")
        print(f"{label:.<34} {str(child.get('status') or 'missing').upper()}")
        failed = child.get("failed_checks") or []
        if failed:
            print(f"  failed checks: {', '.join(failed)}")
        for error in child.get("errors") or []:
            print(f"  error: {error}")
    print("VoiceOver subjective usability..... NOT AUTOMATED")
    print(f"report: {output}")
    print(f"AUTOMATED REAL_ENVIRONMENT: {str(report.get('status')).upper()}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    app = Path(args.app).expanduser().resolve()
    fallback_output = root / "dist" / "evidence" / "real-environment-suite.json"
    output = Path(args.output).expanduser().resolve() if args.output else fallback_output

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "fail",
        "execution_environment": "target-macos-real",
        "fidelity_class": "target_environment",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "app": str(app),
        "source_revision": None,
        "checkout_revision": None,
        "tests": {},
        "errors": [],
        "privacy_boundary": (
            "The aggregate contains status, bounded check names, resource evidence paths "
            "and errors only; transcript and meeting text are not copied into this report."
        ),
        "non_automated_evidence": [
            {
                "id": "voiceover_subjective_usability",
                "status": "human_judgement_if_materially_required",
                "reason": (
                    "Accessibility tree, focus and keyboard paths are automated; spoken-output "
                    "quality and subjective usability cannot be established by this runner."
                ),
            }
        ],
        "remaining_release_actions_after_pass": [
            "Record any materially required subjective VoiceOver/usability observation.",
            "Recheck exact candidate/base freshness and the full dev-to-main diff before promotion.",
        ],
    }

    try:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("REAL_ENVIRONMENT suite requires an Apple-Silicon Mac")
        if not app.is_dir():
            raise RuntimeError(f"app not found: {app}")
        checkout_revision, dirty_entries = measured.git_state(root)
        if dirty_entries:
            raise RuntimeError(
                "REAL_ENVIRONMENT suite requires a clean checkout: "
                + " | ".join(dirty_entries)
            )
        _, manifest = measured.production_manifest_for(app)
        source_revision = str((manifest.get("source") or {}).get("revision") or "")
        if not measured.revisions_match(checkout_revision, source_revision):
            raise RuntimeError(
                "production artifact does not match checkout: "
                f"{source_revision or 'unknown'} != {checkout_revision}"
            )
        report["source_revision"] = source_revision
        report["checkout_revision"] = checkout_revision

        evidence_root = root / "dist" / "evidence" / "measured-release" / source_revision
        if not args.output:
            output = evidence_root / "real-environment-suite.json"
        measured_output = evidence_root / "measured-release-evidence.json"
        contention_output = evidence_root / "record-while-ai-busy-target-mac.json"
        commands = build_commands(
            root,
            app,
            measured_output,
            contention_output,
            args,
        )

        for name, command, child_output, timeout in commands:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(root),
                    check=False,
                    timeout=timeout,
                )
                summary = child_summary(child_output, completed.returncode)
            except subprocess.TimeoutExpired:
                summary = child_summary(child_output, 124)
                summary["status"] = "timeout"
                summary["errors"].append(f"{name} exceeded {int(timeout)} seconds")
            report["tests"][name] = summary

        report["status"] = (
            "pass"
            if all(
                child_passed(report["tests"].get(name, {}))
                for name in ("measured_release", "record_while_ai_busy")
            )
            else "fail"
        )
    except Exception as exc:
        report["errors"].append(str(exc))
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_report(output, report)
        print_summary(report, output)

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
