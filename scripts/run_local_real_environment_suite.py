#!/usr/bin/env python3
"""Run ClosedRoom REAL_ENVIRONMENT evidence without Apple distribution authority.

This command builds or reuses one exact finalized ad-hoc app, runs the canonical
physical measured-release and PRS-16 contention owners through the explicit
local adapter, and writes a privacy-bounded local PASS/FAIL summary.

A PASS here is intentionally *not* release readiness: Developer ID signing,
notarization, stapling and distribution Gatekeeper evidence remain blocked until
Apple Developer Program authority exists.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import local_real_environment_policy as local_policy
import measured_release_target_mac as measured
import run_real_environment_release_suite as aggregate

GENERATED_FRONTEND = Path("src/local_asr_server/static")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--app",
        help="Reuse this exact finalized ad-hoc ClosedRoom.app instead of auto-select/build",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Build a fresh exact ad-hoc app even if one already exists for this revision",
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


def restore_generated_frontend(root: Path) -> None:
    target = GENERATED_FRONTEND.as_posix()
    subprocess.run(
        ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--", target],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "clean", "-fd", "--", target], cwd=root, check=True)


def required_tools_missing() -> list[str]:
    return [name for name in ("uv", "pnpm", "ffmpeg") if shutil.which(name) is None]


def read_last_build(root: Path) -> Path:
    path = root / "dist" / "last-build.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("dist/last-build.json missing after local artifact build") from exc
    app = Path(str(payload.get("app") or "")).expanduser().resolve()
    if not app.is_dir():
        raise RuntimeError(f"local build app missing: {app}")
    return app


def build_local_artifact(root: Path, checkout_revision: str) -> Path:
    env = os.environ.copy()
    env.pop("CLOSEDROOM_SIGN_IDENTITY", None)
    env["CLOSEDROOM_BUILD_CHANNEL"] = "local-real-environment"
    subprocess.run(
        ["bash", "scripts/build_artifact.sh", "--no-dmg"],
        cwd=root,
        env=env,
        check=True,
        timeout=3600,
    )
    restore_generated_frontend(root)

    after_revision, dirty_entries = measured.git_state(root)
    if not local_policy.revisions_match(checkout_revision, after_revision):
        raise RuntimeError(
            f"source revision moved during local build: {checkout_revision} -> {after_revision}"
        )
    if dirty_entries:
        raise RuntimeError(
            "local artifact build left checkout dirty: " + " | ".join(dirty_entries)
        )
    app = read_last_build(root)
    local_policy.local_manifest_for(app)
    return app


def select_local_artifact(
    root: Path,
    checkout_revision: str,
    explicit_app: str | None,
    rebuild: bool,
) -> tuple[Path, Path, dict[str, Any], str]:
    if explicit_app:
        app = Path(explicit_app).expanduser().resolve()
        if not app.is_dir():
            raise RuntimeError(f"app not found: {app}")
        manifest_path, manifest = local_policy.local_manifest_for(app)
        selection = "explicit"
    else:
        found = None if rebuild else local_policy.find_exact_local_app(root, checkout_revision)
        if found is not None:
            app, manifest_path, manifest = found
            selection = "reused_exact"
        else:
            app = build_local_artifact(root, checkout_revision)
            manifest_path, manifest = local_policy.local_manifest_for(app)
            selection = "built_exact"

    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    source_revision = str(source.get("revision") or "")
    if not local_policy.revisions_match(checkout_revision, source_revision):
        raise RuntimeError(
            "local artifact does not match checkout: "
            f"{source_revision or 'unknown'} != {checkout_revision}"
        )
    return app, manifest_path, manifest, selection


def build_commands(
    root: Path,
    app: Path,
    measured_output: Path,
    contention_output: Path,
    args: argparse.Namespace,
) -> list[tuple[str, list[str], Path, float]]:
    base = [sys.executable, "scripts/local_real_environment_child.py"]
    common = ["--root", str(root), "--app", str(app)]
    measured_command = [
        *base,
        "measured_release",
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
        *base,
        "record_while_ai_busy",
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


def print_summary(report: dict[str, Any], output: Path) -> None:
    print("\nClosedRoom LOCAL REAL_ENVIRONMENT suite")
    print(f"candidate: {report.get('checkout_revision') or 'unknown'}")
    print(f"artifact selection: {report.get('artifact_selection') or 'unknown'}")
    for name in ("measured_release", "record_while_ai_busy"):
        child = (report.get("tests") or {}).get(name) or {}
        label = name.replace("_", " ")
        print(f"{label:.<34} {str(child.get('status') or 'missing').upper()}")
        failed = child.get("failed_checks") or []
        if failed:
            print(f"  failed checks: {', '.join(failed)}")
        if child.get("error_count"):
            print(f"  child errors: {child['error_count']} (see child evidence)")
        if child.get("timeout_seconds"):
            print(f"  timeout: {child['timeout_seconds']} seconds")
    print("distribution authority............. BLOCKED (Apple Developer membership)")
    print("VoiceOver subjective usability..... NOT AUTOMATED")
    print("release qualification.............. NOT ESTABLISHED")
    print(f"report: {output}")
    print(f"LOCAL REAL_ENVIRONMENT: {str(report.get('status')).upper()}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    fallback_output = root / "dist" / "evidence" / "local-real-environment-suite.json"
    output = Path(args.output).expanduser().resolve() if args.output else fallback_output

    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "fail",
        "qualification_scope": "local_real_environment",
        "execution_environment": "target-macos-real",
        "fidelity_class": "target_environment",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "checkout_revision": None,
        "source_revision": None,
        "app": None,
        "build_manifest": None,
        "artifact_selection": None,
        "tests": {},
        "errors": [],
        "distribution_authority": {
            "status": "blocked",
            "reason": "apple_developer_program_membership_unavailable",
            "not_tested": [
                "developer_id_distribution_signing",
                "secure_timestamp",
                "app_and_dmg_notarization",
                "stapling",
                "distribution_gatekeeper_assessment",
            ],
        },
        "release_qualification": "not_established",
        "privacy_boundary": (
            "The aggregate contains status, bounded check names and local evidence paths only; "
            "child error payloads, transcript and meeting text are not copied into it."
        ),
        "non_automated_evidence": [
            {
                "id": "voiceover_subjective_usability",
                "status": "human_judgement_if_materially_required",
            }
        ],
    }

    try:
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("LOCAL REAL_ENVIRONMENT requires an Apple-Silicon Mac")
        missing = required_tools_missing()
        if missing:
            raise RuntimeError("missing required tools: " + ", ".join(missing))

        checkout_revision, dirty_entries = measured.git_state(root)
        if dirty_entries:
            raise RuntimeError(
                "LOCAL REAL_ENVIRONMENT requires a clean checkout: "
                + " | ".join(dirty_entries)
            )
        report["checkout_revision"] = checkout_revision

        app, manifest_path, manifest, selection = select_local_artifact(
            root,
            checkout_revision,
            args.app,
            args.rebuild,
        )
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        source_revision = str(source.get("revision") or "")
        report["source_revision"] = source_revision
        report["app"] = str(app)
        report["build_manifest"] = str(manifest_path)
        report["artifact_selection"] = selection

        evidence_root = root / "dist" / "evidence" / "local-real-environment" / source_revision
        if not args.output:
            output = evidence_root / "local-real-environment-suite.json"
        measured_output = evidence_root / "measured-local-real-environment.json"
        contention_output = evidence_root / "record-while-ai-busy-local-real-environment.json"

        for name, command, child_output, timeout in build_commands(
            root,
            app,
            measured_output,
            contention_output,
            args,
        ):
            try:
                completed = subprocess.run(
                    command,
                    cwd=root,
                    check=False,
                    timeout=timeout,
                )
                summary = aggregate.child_summary(child_output, completed.returncode)
            except subprocess.TimeoutExpired:
                summary = aggregate.child_summary(child_output, 124)
                summary["status"] = "timeout"
                summary["timeout_seconds"] = int(timeout)
            report["tests"][name] = summary

        report["status"] = (
            "pass"
            if all(
                aggregate.child_passed(report["tests"].get(name, {}))
                for name in ("measured_release", "record_while_ai_busy")
            )
            else "fail"
        )
    except Exception as exc:
        report["errors"].append(str(exc))
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        aggregate.write_report(output, report)
        print_summary(report, output)

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
