#!/usr/bin/env python3
"""Diagnose the target-Mac Cmd-K search shortcut against an exact ClosedRoom artifact.

This is diagnostic tooling, not release qualification. It reuses the exact app
recorded by a LOCAL REAL_ENVIRONMENT aggregate, launches it with an isolated
HOME, navigates to Home through the same Accessibility contract used by the
release smoke, compares Cmd-K delivery with pressing the same Search control
through Accessibility, and records only privacy-safe process/window/focus-role
metadata.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from macos_ui_driver import AccessibilityPermissionRequired, UIAutomationError, default_driver
from real_environment_smoke import LABELS, Api, discover_server, pids_for, quit_app, wait

DRIVER = default_driver()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose ClosedRoom Cmd-K delivery on a representative target Mac"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--candidate",
        help="Candidate revision whose LOCAL REAL_ENVIRONMENT aggregate should be reused",
    )
    parser.add_argument("--aggregate", help="Explicit local-real-environment-suite.json path")
    parser.add_argument("--evidence", help="Explicit output path")
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args()


def latest_aggregate(root: Path) -> Path:
    parent = root / "dist" / "evidence" / "local-real-environment"
    candidates = sorted(parent.glob("*/local-real-environment-suite.json"), reverse=True)
    if not candidates:
        raise RuntimeError("local_real_environment_aggregate_missing")
    return candidates[0]


def resolve_aggregate(root: Path, candidate: str | None, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
    elif candidate:
        path = (
            root
            / "dist"
            / "evidence"
            / "local-real-environment"
            / candidate[:12]
            / "local-real-environment-suite.json"
        )
    else:
        path = latest_aggregate(root)
    if not path.is_file():
        raise RuntimeError(f"local_real_environment_aggregate_missing:{path}")
    return path


def bundle_info(app: Path) -> dict[str, str]:
    plist = app / "Contents" / "Info.plist"
    with plist.open("rb") as handle:
        info = plistlib.load(handle)
    executable_name = str(info.get("CFBundleExecutable") or "")
    executable = app / "Contents" / "MacOS" / executable_name
    bundle_id = str(info.get("CFBundleIdentifier") or "")
    version = str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "")
    if not bundle_id or not executable_name or not executable.is_file():
        raise RuntimeError("invalid_packaged_app_identity")
    return {"bundle_id": bundle_id, "version": version, "executable": str(executable)}


def manifest_source_revision(manifest: dict[str, Any]) -> str:
    source = manifest.get("source")
    if isinstance(source, dict) and source.get("revision"):
        return str(source["revision"])
    return str(manifest.get("source_revision") or "")


def revisions_match(left: str, right: str) -> bool:
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def focused_role(pid: int) -> str:
    """Return only the AX role, discarding potentially sensitive detail/value."""
    raw = DRIVER.focused(pid)
    return raw.split("|", 1)[0].strip() or "unknown"


def safe_focus_role(pid: int) -> str:
    try:
        return focused_role(pid)
    except Exception as exc:
        return f"error:{type(exc).__name__}"


def safe_diagnostics(pid: int) -> dict[str, Any]:
    try:
        return DRIVER.diagnostics(pid)
    except Exception as exc:
        return {"diagnostic_error": type(exc).__name__}


def snapshot(pid: int) -> dict[str, Any]:
    return {
        "focused_role": safe_focus_role(pid),
        "process_window": safe_diagnostics(pid),
    }


def classify(shortcut_opened: bool, fallback_opened: bool | None) -> str:
    if shortcut_opened:
        return "shortcut_delivery_succeeded"
    if fallback_opened:
        return "shortcut_delivery_failed_search_ui_healthy"
    return "search_ui_or_ax_activation_failed"


def evidence_path(root: Path, revision: str, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        path = (
            root
            / "dist"
            / "evidence"
            / "local-real-environment"
            / revision[:12]
            / "keyboard-shortcut-diagnostic.json"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    aggregate_path = resolve_aggregate(root, args.candidate, args.aggregate)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))

    candidate_revision = str(aggregate.get("checkout_revision") or "")
    app_raw = str(aggregate.get("app") or "")
    manifest_raw = str(aggregate.get("build_manifest") or "")
    if not candidate_revision or not app_raw or not manifest_raw:
        raise RuntimeError("aggregate_missing_exact_artifact_identity")
    if args.candidate and not revisions_match(candidate_revision, args.candidate):
        raise RuntimeError(
            f"aggregate_candidate_mismatch:aggregate={candidate_revision}:requested={args.candidate}"
        )

    app = Path(app_raw).expanduser().resolve()
    manifest_path = Path(manifest_raw).expanduser().resolve()
    if not app.is_dir() or not manifest_path.is_file():
        raise RuntimeError("exact_artifact_or_manifest_missing")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_revision = manifest_source_revision(manifest)
    if not revisions_match(candidate_revision, artifact_revision):
        raise RuntimeError(
            f"artifact_revision_mismatch:candidate={candidate_revision}:artifact={artifact_revision}"
        )

    info = bundle_info(app)
    executable = info["executable"]
    if pids_for(executable):
        raise RuntimeError("exact_artifact_already_running")

    output = evidence_path(root, candidate_revision, args.evidence)
    report: dict[str, Any] = {
        "schema_version": 1,
        "diagnostic": "keyboard_cmd_k_search",
        "status": "error",
        "classification": None,
        "execution_environment": "target-macos-real",
        "fidelity_class": "target_environment",
        "qualification_scope": "diagnostic_only",
        "candidate_revision": candidate_revision,
        "artifact_revision": artifact_revision,
        "app": str(app),
        "aggregate": str(aggregate_path),
        "privacy_boundary": (
            "Evidence contains only bounded status, process/window metadata and focused AX role; "
            "UI labels, titles, input values, transcript text and meeting text are not persisted."
        ),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "errors": [],
        "cleanup": {},
    }

    sandbox_home = Path(tempfile.mkdtemp(prefix="closedroom-keyboard-diagnostic-"))
    process: subprocess.Popen[bytes] | None = None
    pid: int | None = None
    port: int | None = None

    try:
        launch_env = os.environ.copy()
        launch_env["HOME"] = str(sandbox_home)
        process = subprocess.Popen(
            [executable],
            env=launch_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = process.pid
        report["steps"]["packaged_process_started"] = wait(lambda: process.poll() is None, 3)
        if not report["steps"]["packaged_process_started"]:
            raise RuntimeError("packaged_process_did_not_start")

        port, health = discover_server(pid, info["bundle_id"], info["version"], args.timeout)
        Api(port)
        report["steps"]["loopback_health"] = bool(health.get("ok"))
        if not report["steps"]["loopback_health"]:
            raise RuntimeError("loopback_health_failed")

        report["steps"]["wkwebview_window_accessible"] = DRIVER.window_accessible(pid)
        if not report["steps"]["wkwebview_window_accessible"]:
            raise RuntimeError("wkwebview_window_not_accessible")

        # Match the canonical REAL_ENVIRONMENT journey: explicitly navigate to
        # Home before checking the Search control. A fresh isolated HOME may
        # otherwise launch on a different route even though the sidebar is ready.
        home_navigation_available = wait(lambda: DRIVER.exists(pid, LABELS["home"]), args.timeout)
        report["steps"]["home_navigation_available"] = home_navigation_available
        if not home_navigation_available:
            raise RuntimeError("home_navigation_control_missing")
        DRIVER.press(pid, LABELS["home"])

        home_search_available = wait(lambda: DRIVER.exists(pid, LABELS["search"]), args.timeout)
        report["steps"]["home_search_available"] = home_search_available
        if not home_search_available:
            raise RuntimeError("home_search_control_missing_after_navigation")

        report["before_cmd_k"] = snapshot(pid)
        DRIVER.key(pid, "cmd-k")
        shortcut_opened = wait(lambda: DRIVER.exists(pid, LABELS["close"]), 3.0)
        report["steps"]["keyboard_cmd_k_search"] = shortcut_opened
        report["after_cmd_k"] = snapshot(pid)

        fallback_opened: bool | None = None
        if not shortcut_opened:
            DRIVER.press(pid, LABELS["search"])
            fallback_opened = wait(lambda: DRIVER.exists(pid, LABELS["close"]), 3.0)
            report["steps"]["ax_search_button_opens_dialog"] = fallback_opened
            report["after_ax_search_press"] = snapshot(pid)
        else:
            report["steps"]["ax_search_button_opens_dialog"] = "not_needed"

        dialog_open = shortcut_opened or bool(fallback_opened)
        if dialog_open:
            DRIVER.key(pid, "escape")
            report["steps"]["escape_closes_search"] = wait(
                lambda: not DRIVER.exists(pid, LABELS["close"]), 3.0
            )
        else:
            report["steps"]["escape_closes_search"] = "not_applicable"

        report["classification"] = classify(shortcut_opened, fallback_opened)
        report["status"] = "complete"

    except AccessibilityPermissionRequired as exc:
        report["status"] = "blocked_permission"
        report["errors"].append(type(exc).__name__)
    except UIAutomationError as exc:
        report["status"] = "error"
        report["errors"].append(f"ui_automation:{type(exc).__name__}")
    except Exception as exc:
        report["status"] = "error"
        report["errors"].append(f"{type(exc).__name__}:{exc}")
    finally:
        if pid is not None:
            report["cleanup"] = quit_app(pid, executable, port)
        shutil.rmtree(sandbox_home, ignore_errors=True)
        report["cleanup"]["isolated_home_removed"] = not sandbox_home.exists()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Evidence: {output}")
    return 0 if report["status"] == "complete" else 2 if report["status"] == "blocked_permission" else 1


if __name__ == "__main__":
    raise SystemExit(main())
